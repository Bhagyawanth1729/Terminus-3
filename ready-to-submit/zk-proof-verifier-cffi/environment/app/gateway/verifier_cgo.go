package main

/*
#cgo LDFLAGS: -L/app/librust_verifier/target/release -lrust_verifier -ldl -lm
#include "verifier.h"
*/
import "C"
import (
	"unsafe"
)

// VerifyZKProof calls the Rust C-FFI verifier.
// BROKEN: Passes raw pubInputs directly (big-endian and unpadded) without
// padding to 32 bytes and converting to little-endian byte representation.
func VerifyZKProof(proof []byte, pubInputs []byte) int32 {
	if len(proof) == 0 || len(pubInputs) == 0 {
		return -1
	}

	// BROKEN: Passes raw byte slice without padding or byte reversal
	cProof := (*C.uint8_t)(unsafe.Pointer(&proof[0]))
	cProofLen := C.size_t(len(proof))

	cPubInputs := (*C.uint8_t)(unsafe.Pointer(&pubInputs[0]))
	cPubLen := C.size_t(len(pubInputs))

	res := C.zk_verify_proof_c(cProof, cProofLen, cPubInputs, cPubLen)
	return int32(res)
}
