package main

import (
	"fmt"
	"math"
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
		// DEFECT: Floating point conversion of scaled integer price causes IEEE 754 precision loss
		// on large trade quantities and high price thresholds.
		floatPrice := float64(t.PriceScaled) / 100000000.0
		floatValue := floatPrice * float64(t.Quantity)
		totalVolumeScaled += int64(math.Round(floatValue * 100000000.0))
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
	// Simple client helper sending batch summary parameters to Java service
	fmt.Printf("Audit client sending batch: Trades=%d, VolumeScaled=%d, AvgPrice=%.4f\n",
		batch.TotalTrades, batch.TotalVolumeScaled, batch.AvgPrice)
	return nil
}
