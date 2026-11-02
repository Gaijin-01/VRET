// Batched search kernels. Device-side compare of SHA256(candidate)[:64 bits]
// against the PUBLIC challenge; returns only the lowest matching index.
// The hidden target never reaches the device. Frozen verifier is unchanged:
// this implements the same public comparison and is equivalence-tested to it.
typedef unsigned int u32;
typedef unsigned long long u64;
__device__ __constant__ u32 K[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

__device__ __forceinline__ u32 rotr(u32 x, int n) { return (x >> n) | (x << (32 - n)); }

// Padded message byte at absolute position pos of a total-byte padded message.
__device__ __forceinline__ u32 msgbyte(const unsigned char* p, u64 len, u64 total, u64 pos) {
  if (pos < len) return p[pos];
  if (pos == len) return 0x80u;
  if (pos >= total - 8) return (u32)(((len * 8ull) >> ((total - 1 - pos) * 8)) & 0xffull);
  return 0u;
}

// 16-word rolling schedule: no w[64] array, so no local-memory spill after unroll.
__device__ __forceinline__ void compress(u32* h, u32* w) {
  u32 a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
  #pragma unroll
  for (int j = 0; j < 64; j++) {
    u32 wj;
    if (j < 16) wj = w[j];
    else {
      u32 x = w[(j+1)&15], y = w[(j+14)&15];
      wj = w[j&15] + (rotr(x,7)^rotr(x,18)^(x>>3)) + w[(j+9)&15] + (rotr(y,17)^rotr(y,19)^(y>>10));
      w[j&15] = wj;
    }
    u32 t1 = hh + (rotr(e,6)^rotr(e,11)^rotr(e,25)) + ((e&f)^(~e&g)) + K[j] + wj;
    u32 t2 = (rotr(a,2)^rotr(a,13)^rotr(a,22)) + ((a&b)^(a&c)^(b&c));
    hh=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
  }
  h[0]+=a; h[1]+=b; h[2]+=c; h[3]+=d; h[4]+=e; h[5]+=f; h[6]+=g; h[7]+=hh;
}

// offsets has count+1 entries: length(i) = offsets[i+1]-offsets[i].
// Fast path: every payload <= 55 bytes -> exactly one SHA block, no loop.
extern "C" __global__ void __launch_bounds__(256) sha256_match_fast(
    const unsigned char* data, const u32* offsets, u32 count, u64 challenge, u32* result) {
  u32 i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= count) return;
  if (*(volatile u32*)result < i) return;   // cannot be the lowest index: skip (pure optimisation)
  const unsigned char* p = data + offsets[i];
  u32 len = offsets[i+1] - offsets[i];
  u32 w[16];
  #pragma unroll
  for (int j = 0; j < 16; j++)
    w[j] = (msgbyte(p,len,64,4*j)<<24)|(msgbyte(p,len,64,4*j+1)<<16)|(msgbyte(p,len,64,4*j+2)<<8)|msgbyte(p,len,64,4*j+3);
  u32 h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  compress(h, w);
  if ((((u64)h[0] << 32) | h[1]) == challenge) atomicMin(result, i);
}

// Generic multi-block fallback: arbitrary length.
extern "C" __global__ void __launch_bounds__(256) sha256_match_generic(
    const unsigned char* data, const u32* offsets, u32 count, u64 challenge, u32* result) {
  u32 i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= count) return;
  if (*(volatile u32*)result < i) return;
  const unsigned char* p = data + offsets[i];
  u64 len = offsets[i+1] - offsets[i];
  u64 total = ((len + 9 + 63) / 64) * 64;
  u32 h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  for (u64 block = 0; block < total; block += 64) {
    u32 w[16];
    #pragma unroll
    for (int j = 0; j < 16; j++) {
      u64 q = block + 4*j;
      w[j] = (msgbyte(p,len,total,q)<<24)|(msgbyte(p,len,total,q+1)<<16)|(msgbyte(p,len,total,q+2)<<8)|msgbyte(p,len,total,q+3);
    }
    compress(h, w);
  }
  if ((((u64)h[0] << 32) | h[1]) == challenge) atomicMin(result, i);
}

// int64 path: host ships raw values (array('q')); the device formats str(int) itself.
// Identical bytes to Python str(): optional '-', no leading zeros, "0" for zero. <= 20 bytes -> one block.
extern "C" __global__ void __launch_bounds__(256) sha256_match_i64(
    const long long* vals, u32 count, u64 challenge, u32* result) {
  u32 i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= count) return;
  if (*(volatile u32*)result < i) return;
  long long v = vals[i];
  bool neg = v < 0;
  u64 u = neg ? (u64)(-(v + 1)) + 1ull : (u64)v;     // safe for LLONG_MIN
  unsigned char tmp[20]; u32 n = 0;
  do { tmp[n++] = (unsigned char)('0' + (u % 10ull)); u /= 10ull; } while (u);
  unsigned char buf[24]; u32 len = n + (neg ? 1u : 0u);
  if (neg) buf[0] = '-';
  for (u32 k = 0; k < n; k++) buf[(neg ? 1u : 0u) + k] = tmp[n - 1 - k];
  u32 w[16];
  #pragma unroll
  for (int j = 0; j < 16; j++) {
    u32 x = 0;
    #pragma unroll
    for (int k = 0; k < 4; k++) {
      u32 pos = 4*j + k, b;
      if (pos < len) b = buf[pos];
      else if (pos == len) b = 0x80u;
      else if (pos >= 60) b = ((len * 8u) >> ((63 - pos) * 8)) & 0xffu;
      else b = 0u;
      x = (x << 8) | b;
    }
    w[j] = x;
  }
  u32 h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  compress(h, w);
  if ((((u64)h[0] << 32) | h[1]) == challenge) atomicMin(result, i);
}
