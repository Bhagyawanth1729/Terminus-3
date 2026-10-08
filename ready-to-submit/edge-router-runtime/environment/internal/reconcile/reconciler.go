package reconcile

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"edge-router-runtime/internal/checkpoint"
	"edge-router-runtime/internal/compiler"
	"edge-router-runtime/internal/config"
	"edge-router-runtime/internal/drain"
	rt "edge-router-runtime/internal/runtime"
	"edge-router-runtime/internal/telemetry"
)

type Reconciler struct {
	compiler          *compiler.Compiler
	store             *rt.PublicationStore
	checkpoints       *checkpoint.Store
	drains            *drain.Manager
	telemetry         *telemetry.Registry
	writer            sync.Mutex
	acceptedMu        sync.RWMutex
	acceptedRevision  map[string]uint64
	acceptedDigest    map[string]string
	generation        atomic.Uint64
	incMu             sync.Mutex
	incarnations      map[string]uint64
	retired           map[string]*rt.EndpointRuntime
}

func New(
	c *compiler.Compiler,
	s *rt.PublicationStore,
	cp *checkpoint.Store,
	d *drain.Manager,
	t *telemetry.Registry,
) *Reconciler {
	return &Reconciler{
		compiler:         c,
		store:            s,
		checkpoints:      cp,
		drains:           d,
		telemetry:        t,
		acceptedRevision: map[string]uint64{},
		acceptedDigest:   map[string]string{},
		incarnations:     map[string]uint64{},
		retired:          map[string]*rt.EndpointRuntime{},
	}
}

func (r *Reconciler) Current() *rt.RuntimeSnapshot {
	return r.store.Current()
}

func (r *Reconciler) AcceptedRevision(source string) uint64 {
	r.acceptedMu.RLock()
	defer r.acceptedMu.RUnlock()
	return r.acceptedRevision[source]
}

func (r *Reconciler) Process(ctx context.Context, candidate config.Candidate) config.SubmitResult {
	_ = ctx
	currentRev := r.AcceptedRevision(candidate.Source)
	if candidate.Revision < currentRev {
		return config.SubmitResult{
			Source:   candidate.Source,
			Revision: candidate.Revision,
			Digest:   candidate.Digest,
			Outcome:  "stale",
		}
	}

	r.acceptedMu.Lock()
	r.acceptedRevision[candidate.Source] = candidate.Revision
	r.acceptedDigest[candidate.Source] = candidate.Digest
	r.acceptedMu.Unlock()

	compiled, err := r.compiler.Compile(candidate.Document)
	if err != nil {
		r.generation.Add(1)
		r.telemetry.Counter("edge_update_rejected_total", map[string]string{"source": candidate.Source}).Inc()
		return config.SubmitResult{
			Source:   candidate.Source,
			Revision: candidate.Revision,
			Digest:   candidate.Digest,
			Outcome:  "rejected",
			Message:  err.Error(),
		}
	}

	r.writer.Lock()
	defer r.writer.Unlock()
	return r.publish(candidate, compiled)
}

func (r *Reconciler) publish(candidate config.Candidate, compiled *compiler.Result) config.SubmitResult {
	old := r.store.Current()
	if candidate.Revision == r.acceptedRevision[candidate.Source] &&
		candidate.Digest == r.acceptedDigest[candidate.Source] && old != nil {
		r.telemetry.Counter("edge_update_duplicate_seen_total", map[string]string{"source": candidate.Source}).Inc()
	}

	generation := r.generation.Add(1)
	if old != nil && generation <= old.Generation {
		generation = old.Generation + 1
		r.generation.Store(generation)
	}

	pools := map[string]*rt.PoolRuntime{}
	oldPools := map[string]*rt.PoolRuntime{}
	if old != nil {
		for id, pool := range old.Pools {
			oldPools[id] = pool
		}
	}

	for id, cfg := range compiled.PoolConfigs {
		existing := oldPools[id]
		pool, err := r.buildPool(cfg, existing)
		if err != nil {
			return config.SubmitResult{
				Source:   candidate.Source,
				Revision: candidate.Revision,
				Digest:   candidate.Digest,
				Outcome:  "rejected",
				Message:  err.Error(),
			}
		}
		pools[id] = pool
	}

	snapshot := &rt.RuntimeSnapshot{
		Generation:      generation,
		CreatedAt:       time.Now(),
		Routes:          compiled.Routes,
		Pools:           pools,
		PoolConfigs:     compiled.PoolConfigs,
		SourceRevisions: compiled.SourceRevisions,
		SourceDigests:   compiled.SourceDigests,
		Desired:         compiled.Desired,
		Digest:          compiled.Digest,
	}
	cp := checkpoint.Checkpoint{
		Generation:      generation,
		AcceptedSources: compiled.Desired.Sources,
		Desired:         compiled.Desired,
		Digest:          compiled.Digest,
	}
	if _, err := r.checkpoints.Prepare(cp); err != nil {
		return config.SubmitResult{
			Source:   candidate.Source,
			Revision: candidate.Revision,
			Digest:   candidate.Digest,
			Outcome:  "rejected",
			Message:  "checkpoint prepare: " + err.Error(),
		}
	}

	r.store.Publish(snapshot)
	r.telemetry.RegisterScope("generation", fmt.Sprintf("%d", generation))
	r.telemetry.Gauge("edge_current_generation", nil).Set(int64(generation))
	r.telemetry.Counter("edge_update_accepted_total", map[string]string{"source": candidate.Source}).Inc()
	r.retireRemoved(old, snapshot)
	_ = r.checkpoints.Commit(generation)

	return config.SubmitResult{
		Source:   candidate.Source,
		Revision: candidate.Revision,
		Digest:   candidate.Digest,
		Outcome:  "accepted",
	}
}

func (r *Reconciler) buildPool(cfg config.Pool, existing *rt.PoolRuntime) (*rt.PoolRuntime, error) {
	fingerprint := config.PoolCompatibility(cfg)
	if existing != nil && existing.Fingerprint == fingerprint {
		existing.Strategy = cfg.Strategy
		existing.Affinity = cfg.Affinity
		return existing, nil
	}

	pool := rt.NewPoolRuntime(cfg.ID, fingerprint, cfg.Strategy, cfg.Affinity)
	for _, epcfg := range cfg.Endpoints {
		identity, err := config.NormalizeAddress(epcfg.Address, cfg.Transport.Scheme)
		if err != nil {
			return nil, err
		}
		key := cfg.ID + "|" + identity

		r.incMu.Lock()
		incarnation := r.incarnations[key]
		if incarnation == 0 {
			incarnation = 1
			r.incarnations[key] = incarnation
		}
		old := r.retired[key]
		r.incMu.Unlock()

		if old != nil {
			old.Reactivate()
			old.Weight = epcfg.Weight
			old.Zone = epcfg.Zone
			pool.Endpoints = append(pool.Endpoints, old)
			continue
		}

		pool.Endpoints = append(
			pool.Endpoints,
			rt.NewEndpointRuntime(cfg.ID, identity, epcfg.Address, incarnation, epcfg.Weight, epcfg.Zone),
		)
		r.telemetry.RegisterScope("endpoint", fmt.Sprintf("%s#%d", key, incarnation))
	}
	return pool, nil
}

func (r *Reconciler) retireRemoved(old, next *rt.RuntimeSnapshot) {
	if old == nil {
		return
	}
	present := map[string]struct{}{}
	for _, pool := range next.Pools {
		for _, endpoint := range pool.Endpoints {
			present[endpoint.PoolID+"|"+endpoint.Identity] = struct{}{}
		}
	}
	deadline := time.Now().Add(time.Duration(max(next.Desired.Defaults.DrainTimeoutMS, 5000)) * time.Millisecond)
	for _, pool := range old.Pools {
		for _, endpoint := range pool.Endpoints {
			key := endpoint.PoolID + "|" + endpoint.Identity
			if _, ok := present[key]; ok {
				continue
			}
			r.incMu.Lock()
			r.retired[key] = endpoint
			r.incMu.Unlock()
			r.drains.Start(endpoint, deadline)
		}
	}
}

func (r *Reconciler) RestoreMetadata(generation uint64, sources []config.SourceState) {
	r.generation.Store(generation)
	r.acceptedMu.Lock()
	for _, source := range sources {
		r.acceptedRevision[source.Name] = source.Revision
		r.acceptedDigest[source.Name] = source.Digest
	}
	r.acceptedMu.Unlock()
}

func (r *Reconciler) Status() map[string]any {
	r.acceptedMu.RLock()
	defer r.acceptedMu.RUnlock()
	revisions := map[string]uint64{}
	for key, value := range r.acceptedRevision {
		revisions[key] = value
	}
	return map[string]any{
		"generation":         r.generation.Load(),
		"accepted_revisions": revisions,
		"draining":           r.drains.Pending(),
	}
}
