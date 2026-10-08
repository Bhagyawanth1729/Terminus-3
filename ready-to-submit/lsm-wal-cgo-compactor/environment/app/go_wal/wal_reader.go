package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"os"
)

type Record struct {
	Metric string
	Host   string
	Ts     int64
	Val    float64
}

func ReadWALFile(filepath string) ([]Record, []byte, error) {
	data, err := os.ReadFile(filepath)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to read WAL file: %w", err)
	}

	buf := bytes.NewReader(data)
	var records []Record

	for buf.Len() > 0 {
		var metricLen uint16
		if err := binary.Read(buf, binary.BigEndian, &metricLen); err != nil {
			if err == io.EOF {
				break
			}
			return nil, nil, err
		}
		metricBytes := make([]byte, metricLen)
		if _, err := io.ReadFull(buf, metricBytes); err != nil {
			return nil, nil, err
		}

		var hostLen uint16
		if err := binary.Read(buf, binary.BigEndian, &hostLen); err != nil {
			return nil, nil, err
		}
		hostBytes := make([]byte, hostLen)
		if _, err := io.ReadFull(buf, hostBytes); err != nil {
			return nil, nil, err
		}

		var ts int64
		if err := binary.Read(buf, binary.BigEndian, &ts); err != nil {
			return nil, nil, err
		}

		var val float64
		if err := binary.Read(buf, binary.BigEndian, &val); err != nil {
			return nil, nil, err
		}

		records = append(records, Record{
			Metric: string(metricBytes),
			Host:   string(hostBytes),
			Ts:     ts,
			Val:    val,
		})
	}

	return records, data, nil
}
