package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

type CredentialPayload struct {
	ID          string `json:"id"`
	PublicScalar string `json:"public_scalar"`
	ProofHex     string `json:"proof_hex"`
}

func main() {
	if len(os.Args) < 3 || os.Args[1] != "--verify" {
		fmt.Println("Usage: gateway --verify <path-to-credential-json>")
		os.Exit(1)
	}

	jsonPath := os.Args[2]
	data, err := os.ReadFile(jsonPath)
	if err != nil {
		fmt.Printf("Error reading file %s: %v\n", jsonPath, err)
		os.Exit(1)
	}

	var creds []CredentialPayload
	if err := json.Unmarshal(data, &creds); err != nil {
		fmt.Printf("Error unmarshaling json: %v\n", err)
		os.Exit(1)
	}

	validCount := 0
	errorCount := 0

	for _, cred := range creds {
		proofBytes, err := hex.DecodeString(cred.ProofHex)
		if err != nil {
			fmt.Printf("Cred %s invalid proof hex\n", cred.ID)
			errorCount++
			continue
		}

		pubBytes, err := hex.DecodeString(cred.PublicScalar)
		if err != nil {
			fmt.Printf("Cred %s invalid public scalar hex\n", cred.ID)
			errorCount++
			continue
		}

		status := VerifyZKProof(proofBytes, pubBytes)
		if status == 1 {
			fmt.Printf("Cred %s: VERIFIED\n", cred.ID)
			validCount++
		} else if status == 0 {
			fmt.Printf("Cred %s: REJECTED\n", cred.ID)
		} else {
			fmt.Printf("Cred %s: ERROR (%d)\n", cred.ID, status)
			errorCount++
		}
	}

	fmt.Printf("Summary: %d verified, %d rejected, %d errors out of %d total\n",
		validCount, len(creds)-validCount-errorCount, errorCount, len(creds))
}
