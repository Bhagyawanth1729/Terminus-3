package main

import (
	"context"
	"errors"
	"fmt"
	"time"
)

type StreamProcessor struct {
	shmPath string
}

func NewStreamProcessor(shmPath string) *StreamProcessor {
	return &StreamProcessor{shmPath: shmPath}
}

func (sp *StreamProcessor) ProcessStream(ctx context.Context, maxTrades int) (TradeBatch, error) {
	reader, err := NewRingReader(sp.shmPath)
	if err != nil {
		return TradeBatch{}, err
	}

	// DEFECT: Missing defer reader.Free() or handle cleanup on early context cancellation / error!
	// If context is done or error occurs mid-stream, reader handle is never freed.

	trades := make([]Trade, 0, maxTrades)
	timeout := time.After(3 * time.Second)

	for len(trades) < maxTrades {
		select {
		case <-ctx.Done():
			// DEFECT: Exits immediately without freeing reader!
			return TradeBatch{}, ctx.Err()
		case <-timeout:
			if len(trades) == 0 {
				return TradeBatch{}, errors.New("stream timeout waiting for trades")
			}
			goto DONE
		default:
			if trade, ok := reader.ReadNext(); ok {
				trades = append(trades, *trade)
			} else {
				time.Sleep(10 * time.Millisecond)
			}
		}
	}

DONE:
	batch := AggregateTrades(trades)
	reader.Free() // Only freed on happy path!
	return batch, nil
}
