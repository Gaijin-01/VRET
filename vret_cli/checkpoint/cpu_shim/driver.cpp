#include "shim.h"
#include "../sha256_batch.cu"
extern "C" void shim_launch(int generic, unsigned grid, unsigned block, const unsigned char* data,
                            const unsigned* offsets, unsigned count, unsigned long long challenge, unsigned* result) {
  blockDim = {block, 1, 1};
  for (unsigned b = 0; b < grid; b++) for (unsigned t = 0; t < block; t++) {
    blockIdx = {b, 0, 0}; threadIdx = {t, 0, 0};
    (generic ? sha256_match_generic : sha256_match_fast)(data, offsets, count, challenge, result);
  }
}
extern "C" void shim_launch_i64(unsigned grid, unsigned block, const long long* vals, unsigned count,
                                unsigned long long challenge, unsigned* result) {
  blockDim = {block, 1, 1};
  for (unsigned b = 0; b < grid; b++) for (unsigned t = 0; t < block; t++) {
    blockIdx = {b, 0, 0}; threadIdx = {t, 0, 0};
    sha256_match_i64(vals, count, challenge, result);
  }
}
