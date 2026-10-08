#ifndef VERIFIER_H
#define VERIFIER_H

#include <stdint.h>
#include <stddef.h>

int32_t zk_verify_proof_c(
    const uint8_t *proof_ptr,
    size_t proof_len,
    const uint8_t *pub_inputs_ptr,
    size_t pub_len
);

#endif // VERIFIER_H
