package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"

	"ciserver.local/ciserver/internal/api"
	"ciserver.local/ciserver/internal/config"
	"ciserver.local/ciserver/internal/store"
)

func main() {
	configPath := flag.String("config", "/app/var/ci-server/etc/ci-server.json", "path to the CI control-plane configuration file")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ci-server: configuration rejected: %v\n", err)
		os.Exit(2)
	}

	st, err := store.Open(cfg.StateDir, cfg.DefaultMaxConcurrent)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ci-server: state directory unusable: %v\n", err)
		os.Exit(3)
	}

	srv := &http.Server{
		Addr:    cfg.Listen,
		Handler: api.New(cfg, st),
	}

	log.Printf("ci-server %s listening on %s (state=%s digest=%s)", cfg.Version, cfg.Listen, cfg.StateDir, cfg.Digest)
	if err := srv.ListenAndServe(); err != nil {
		fmt.Fprintf(os.Stderr, "ci-server: %v\n", err)
		os.Exit(1)
	}
}
