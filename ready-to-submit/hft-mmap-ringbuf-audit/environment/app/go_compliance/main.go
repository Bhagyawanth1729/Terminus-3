package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"time"
)

type OutputPayload struct {
	Status             string  `json:"status"`
	TotalTrades        int64   `json:"total_trades"`
	TotalVolumeScaled  int64   `json:"total_volume_scaled"`
	AveragePrice       string  `json:"average_price"`
}

func main() {
	shmPath := "/tmp/orderbook_ring.buf"
	if len(os.Args) > 1 {
		shmPath = os.Args[1]
	}

	expectedTrades := 1000
	if len(os.Args) > 2 {
		if val, err := strconv.Atoi(os.Args[2]); err == nil {
			expectedTrades = val
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	sp := NewStreamProcessor(shmPath)
	batch, err := sp.ProcessStream(ctx, expectedTrades)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error processing trade stream: %v\n", err)
		os.Exit(1)
	}

	// Write intermediate payload for Java audit service or final output writer
	intermediatePath := "/tmp/intermediate_batch.json"
	data, _ := json.MarshalIndent(batch, "", "  ")
	os.WriteFile(intermediatePath, data, 0644)

	fmt.Printf("Go Compliance Process Completed: Trades=%d, VolumeScaled=%d\n",
		batch.TotalTrades, batch.TotalVolumeScaled)
}
