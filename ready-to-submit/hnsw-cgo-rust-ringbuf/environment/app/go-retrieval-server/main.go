package main

import (
	"context"
	"encoding/binary"
	"flag"
	"fmt"
	"io"
	"log"
	"math"
	"os"
)

func readEmbeddings(path string) ([]uint64, [][]float32, int, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, 0, err
	}
	defer f.Close()

	var numElements, dim uint32
	if err := binary.Read(f, binary.LittleEndian, &numElements); err != nil {
		return nil, nil, 0, err
	}
	if err := binary.Read(f, binary.LittleEndian, &dim); err != nil {
		return nil, nil, 0, err
	}

	ids := make([]uint64, numElements)
	vectors := make([][]float32, numElements)

	for i := 0; i < int(numElements); i++ {
		var id uint64
		if err := binary.Read(f, binary.LittleEndian, &id); err != nil {
			return nil, nil, 0, err
		}
		ids[i] = id
		vec := make([]float32, dim)
		for j := 0; j < int(dim); j++ {
			var valBits uint32
			if err := binary.Read(f, binary.LittleEndian, &valBits); err != nil {
				return nil, nil, 0, err
			}
			vec[j] = math.Float32frombits(valBits)
		}
		vectors[i] = vec
	}

	return ids, vectors, int(dim), nil
}

func readQueries(path string) ([][]float32, int, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, 0, err
	}
	defer f.Close()

	var numQueries, dim uint32
	if err := binary.Read(f, binary.LittleEndian, &numQueries); err != nil {
		return nil, 0, err
	}
	if err := binary.Read(f, binary.LittleEndian, &dim); err != nil {
		return nil, 0, err
	}

	queries := make([][]float32, numQueries)
	for i := 0; i < int(numQueries); i++ {
		vec := make([]float32, dim)
		for j := 0; j < int(dim); j++ {
			var valBits uint32
			if err := binary.Read(f, binary.LittleEndian, &valBits); err != nil {
				if err == io.EOF {
					break
				}
				return nil, 0, err
			}
			vec[j] = math.Float32frombits(valBits)
		}
		queries[i] = vec
	}

	return queries, int(dim), nil
}

func main() {
	embPath := flag.String("embeddings", "/app/dataset/embeddings.bin", "Path to binary embeddings")
	queryPath := flag.String("queries", "/app/dataset/queries.bin", "Path to binary queries")
	ringPath := flag.String("ringbuf", "/tmp/hnsw_ring.buf", "Path to shared memory ring buffer")
	k := flag.Int("k", 10, "Top K results")
	flag.Parse()

	log.Printf("Loading embeddings from %s...", *embPath)
	ids, vectors, dim, err := readEmbeddings(*embPath)
	if err != nil {
		log.Fatalf("Failed to read embeddings: %v", err)
	}

	log.Printf("Loading queries from %s...", *queryPath)
	queries, qDim, err := readQueries(*queryPath)
	if err != nil {
		log.Fatalf("Failed to read queries: %v", err)
	}
	if dim != qDim {
		log.Fatalf("Dimension mismatch: embeddings=%d queries=%d", dim, qDim)
	}

	log.Printf("Initializing Rust HNSW index (dim=%d, max_elements=%d)...", dim, len(ids))
	bridge, err := NewHnswBridge(uint32(dim), size_t(len(ids)), *ringPath, 2048)
	if err != nil {
		log.Fatalf("Bridge init error: %v", err)
	}

	log.Printf("Populating %d points into HNSW index...", len(ids))
	for i := 0; i < len(ids); i++ {
		if !bridge.AddPoint(ids[i], vectors[i]) {
			log.Fatalf("Failed to add point %d (ID %d)", i, ids[i])
		}
	}

	handler := NewSearchStreamHandler(bridge)
	ctx := context.Background()

	log.Printf("Processing %d query vectors through search stream...", len(queries))
	results, err := handler.ProcessQueryBatch(ctx, queries, *k)
	if err != nil {
		log.Fatalf("Query batch processing failed: %v", err)
	}

	log.Printf("Successfully processed query batch. Results streamed to %s", *ringPath)
	_ = results
}
