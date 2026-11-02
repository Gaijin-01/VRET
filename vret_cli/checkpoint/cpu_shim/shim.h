// Compiles the REAL sha256_batch.cu as host C++ and emulates the launch grid.
// Tests kernel logic (padding, compare, atomicMin, early-skip). NOT a CUDA/NVRTC test.
#pragma once
#define __global__
#define __device__
#define __constant__
#define __forceinline__ inline
#define __launch_bounds__(x)
struct Dim3 { unsigned x, y, z; };
static thread_local Dim3 blockIdx, threadIdx, blockDim;
static inline unsigned atomicMin(unsigned* p, unsigned v) {
  unsigned old = __atomic_load_n(p, __ATOMIC_RELAXED);
  while (v < old && !__atomic_compare_exchange_n(p, &old, v, false, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {}
  return old;
}
