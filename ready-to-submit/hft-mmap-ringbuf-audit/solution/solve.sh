#!/bin/bash
set -e

echo "=== Applying fixes to hft-mmap-ringbuf-audit ==="

# 1. Fix Rust atomic store ordering in ringbuf.rs (Ordering::Relaxed -> Ordering::Release)
sed -i 's/header\.head\.store(head + 1, Ordering::Relaxed);/header\.head\.store(head + 1, Ordering::Release);/g' /app/rust_engine/src/ringbuf.rs

# 2. Fix Go fixed-point financial precision in grpc_client.go
cat << 'EOF' > /app/go_compliance/grpc_client.go
package main

import (
	"fmt"
)

type TradeBatch struct {
	TotalTrades       int64
	TotalVolumeScaled int64
	AvgPrice          float64
}

func AggregateTrades(trades []Trade) TradeBatch {
	if len(trades) == 0 {
		return TradeBatch{}
	}

	var totalVolumeScaled int64 = 0
	var sumPriceScaled int64 = 0

	for _, t := range trades {
		totalVolumeScaled += t.PriceScaled * int64(t.Quantity)
		sumPriceScaled += t.PriceScaled
	}

	avgPrice := (float64(sumPriceScaled) / float64(len(trades))) / 100000000.0

	return TradeBatch{
		TotalTrades:       int64(len(trades)),
		TotalVolumeScaled: totalVolumeScaled,
		AvgPrice:          avgPrice,
	}
}

func SendAuditPayload(host string, port int, batch TradeBatch) error {
	fmt.Printf("Audit client sending batch: Trades=%d, VolumeScaled=%d, AvgPrice=%.4f\n",
		batch.TotalTrades, batch.TotalVolumeScaled, batch.AvgPrice)
	return nil
}
EOF

# 3. Fix Go stream handler resource leak (add defer reader.Free())
cat << 'EOF' > /app/go_compliance/stream_handler.go
package main

import (
	"context"
	"errors"
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
	defer reader.Free()

	trades := make([]Trade, 0, maxTrades)
	timeout := time.After(5 * time.Second)

	for len(trades) < maxTrades {
		select {
		case <-ctx.Done():
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
				time.Sleep(1 * time.Millisecond)
			}
		}
	}

DONE:
	batch := AggregateTrades(trades)
	return batch, nil
}
EOF

# 4. Fix Java Locale formatting in AuditService.java
sed -i 's/String\.format(/String\.format(Locale\.US, /g' /app/java_audit/src/main/java/com/terminus/audit/AuditService.java

# 5. Rebuild and run pipeline
cd /app
chmod +x build_all.sh run_pipeline.sh
/app/build_all.sh
/app/run_pipeline.sh /app/data/ticks_sample.bin /app/output.json 1000

echo "=== Solution applied successfully ==="
