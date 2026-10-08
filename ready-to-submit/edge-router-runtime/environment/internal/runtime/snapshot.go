package runtime

import (
    "errors"
    "fmt"
    "sync"
    "sync/atomic"
    "time"

    "edge-router-runtime/internal/config"
)

type HealthState int
const (
    HealthUnknown HealthState = iota
    HealthHealthy
    HealthUnhealthy
)

type Lifecycle int
const (
    LifecycleActive Lifecycle = iota
    LifecycleDraining
    LifecycleRetired
)

type EndpointRuntime struct {
    Identity string
    Address string
    Incarnation uint64
    PoolID string
    Weight int
    Zone string
    mu sync.RWMutex
    health HealthState
    lifecycle Lifecycle
    successes int
    failures int
    inflight int64
    drainDeadline time.Time
    lastChange time.Time
}

func NewEndpointRuntime(poolID, identity, address string, incarnation uint64, weight int, zone string) *EndpointRuntime {
    return &EndpointRuntime{Identity:identity, Address:address, Incarnation:incarnation, PoolID:poolID, Weight:weight, Zone:zone, health:HealthUnknown, lifecycle:LifecycleActive, lastChange:time.Now()}
}

func (e *EndpointRuntime) Health() HealthState { e.mu.RLock(); defer e.mu.RUnlock(); return e.health }
func (e *EndpointRuntime) Lifecycle() Lifecycle { e.mu.RLock(); defer e.mu.RUnlock(); return e.lifecycle }
func (e *EndpointRuntime) Inflight() int64 { return atomic.LoadInt64(&e.inflight) }
func (e *EndpointRuntime) Begin() bool { if e.Lifecycle()==LifecycleRetired { return false }; atomic.AddInt64(&e.inflight,1); return true }
func (e *EndpointRuntime) End() { atomic.AddInt64(&e.inflight,-1) }
func (e *EndpointRuntime) MarkHealthy() { e.mu.Lock(); e.successes++; e.failures=0; e.health=HealthHealthy; e.lastChange=time.Now(); e.mu.Unlock() }
func (e *EndpointRuntime) MarkFailure(threshold int) { e.mu.Lock(); e.failures++; e.successes=0; if e.failures>=threshold { e.health=HealthUnhealthy; e.lastChange=time.Now() }; e.mu.Unlock() }
func (e *EndpointRuntime) MarkUnknown() { e.mu.Lock(); e.health=HealthUnknown; e.successes=0; e.failures=0; e.lastChange=time.Now(); e.mu.Unlock() }
func (e *EndpointRuntime) StartDrain(deadline time.Time) { e.mu.Lock(); e.lifecycle=LifecycleDraining; e.drainDeadline=deadline; e.lastChange=time.Now(); e.mu.Unlock() }
func (e *EndpointRuntime) Reactivate() { e.mu.Lock(); e.lifecycle=LifecycleActive; e.lastChange=time.Now(); e.mu.Unlock() }
func (e *EndpointRuntime) Retire() { e.mu.Lock(); e.lifecycle=LifecycleRetired; e.lastChange=time.Now(); e.mu.Unlock() }
func (e *EndpointRuntime) DrainDeadline() time.Time { e.mu.RLock(); defer e.mu.RUnlock(); return e.drainDeadline }

type PoolRuntime struct {
    ID string
    Fingerprint string
    Strategy string
    Affinity config.AffinityPolicy
    Endpoints []*EndpointRuntime
    mu sync.Mutex
    rr uint64
    sticky map[string]StickyEntry
}

type StickyEntry struct {
    EndpointIdentity string
    Incarnation uint64
    ExpiresAt time.Time
    LastUsed time.Time
}

func NewPoolRuntime(id, fingerprint, strategy string, affinity config.AffinityPolicy) *PoolRuntime {
    return &PoolRuntime{ID:id,Fingerprint:fingerprint,Strategy:strategy,Affinity:affinity,sticky:map[string]StickyEntry{}}
}

func (p *PoolRuntime) NextIndex(n int) int { if n<=0 { return -1 }; p.mu.Lock(); defer p.mu.Unlock(); idx:=int(p.rr%uint64(n)); p.rr++; return idx }
func (p *PoolRuntime) Sticky(key string) (StickyEntry,bool) { p.mu.Lock(); defer p.mu.Unlock(); v,ok:=p.sticky[key]; if ok { v.LastUsed=time.Now(); p.sticky[key]=v }; return v,ok }
func (p *PoolRuntime) PutSticky(key string, e StickyEntry, capacity int) { p.mu.Lock(); defer p.mu.Unlock(); if capacity<=0 { capacity=4096 }; if len(p.sticky)>=capacity { var oldest string; var t time.Time; for k,v:=range p.sticky { if oldest==""||v.LastUsed.Before(t) { oldest=k;t=v.LastUsed } }; delete(p.sticky,oldest) }; p.sticky[key]=e }
func (p *PoolRuntime) PurgeExpired(now time.Time) { p.mu.Lock(); defer p.mu.Unlock(); for k,v:=range p.sticky { if !v.ExpiresAt.IsZero()&&now.After(v.ExpiresAt) { delete(p.sticky,k) } } }
func (p *PoolRuntime) StickyCount() int { p.mu.Lock(); defer p.mu.Unlock(); return len(p.sticky) }

type CompiledRoute struct {
    ID string
    Hosts map[string]struct{}
    PathPrefix string
    Methods map[string]struct{}
    Headers []config.HeaderMatch
    PoolID string
    Failover []string
    Retry config.RetryPolicy
    Affinity config.AffinityPolicy
    Priority int
    Digest string
}

type RuntimeSnapshot struct {
    Generation uint64
    CreatedAt time.Time
    Routes []*CompiledRoute
    Pools map[string]*PoolRuntime
    PoolConfigs map[string]config.Pool
    SourceRevisions map[string]uint64
    SourceDigests map[string]string
    Desired config.Document
    Digest string
    refs atomic.Int64
}

func (s *RuntimeSnapshot) Acquire() *RuntimeSnapshot { if s!=nil { s.refs.Add(1) }; return s }
func (s *RuntimeSnapshot) Release() { if s!=nil { s.refs.Add(-1) } }
func (s *RuntimeSnapshot) References() int64 { if s==nil { return 0 }; return s.refs.Load() }
func (s *RuntimeSnapshot) Pool(id string) (*PoolRuntime,bool) { if s==nil { return nil,false }; p,ok:=s.Pools[id]; return p,ok }

type PublicationStore struct {
    routes atomic.Pointer[routeSet]
    pools atomic.Pointer[poolSet]
    generation atomic.Uint64
    current atomic.Pointer[RuntimeSnapshot]
    mu sync.Mutex
    history []*RuntimeSnapshot
    historyLimit int
}

type routeSet struct { routes []*CompiledRoute }
type poolSet struct { pools map[string]*PoolRuntime; configs map[string]config.Pool }

func NewPublicationStore(limit int) *PublicationStore { if limit<2 { limit=8 }; return &PublicationStore{historyLimit:limit} }

func (p *PublicationStore) Publish(s *RuntimeSnapshot) {
    if s==nil { return }
    p.routes.Store(&routeSet{routes:s.Routes})
    p.generation.Store(s.Generation)
    p.pools.Store(&poolSet{pools:s.Pools,configs:s.PoolConfigs})
    p.current.Store(s)
    p.mu.Lock()
    p.history=append(p.history,s)
    if len(p.history)>p.historyLimit { p.history=p.history[len(p.history)-p.historyLimit:] }
    p.mu.Unlock()
}

func (p *PublicationStore) Current() *RuntimeSnapshot { return p.current.Load() }
func (p *PublicationStore) Acquire() *RuntimeSnapshot { s:=p.current.Load(); if s==nil { return nil }; return s.Acquire() }
func (p *PublicationStore) Generation() uint64 { return p.generation.Load() }
func (p *PublicationStore) Routes() []*CompiledRoute { r:=p.routes.Load(); if r==nil { return nil }; return r.routes }
func (p *PublicationStore) GlobalPool(id string) (*PoolRuntime,bool) { ps:=p.pools.Load(); if ps==nil { return nil,false }; v,ok:=ps.pools[id]; return v,ok }
func (p *PublicationStore) GlobalPoolConfig(id string) (config.Pool,bool) { ps:=p.pools.Load(); if ps==nil { return config.Pool{},false }; v,ok:=ps.configs[id]; return v,ok }
func (p *PublicationStore) History() []*RuntimeSnapshot { p.mu.Lock(); defer p.mu.Unlock(); out:=make([]*RuntimeSnapshot,len(p.history)); copy(out,p.history); return out }
func (p *PublicationStore) ReachableGeneration(g uint64) bool { p.mu.Lock(); defer p.mu.Unlock(); for _,s:=range p.history { if s.Generation==g && s.References()>0 { return true } }; return false }

func BuildPoolRuntime(cfg config.Pool, existing *PoolRuntime, incarnation func(string)uint64) (*PoolRuntime,error) {
    fingerprint:=config.PoolCompatibility(cfg)
    if existing!=nil && existing.Fingerprint==fingerprint { existing.Strategy=cfg.Strategy; existing.Affinity=cfg.Affinity; return existing,nil }
    p:=NewPoolRuntime(cfg.ID,fingerprint,cfg.Strategy,cfg.Affinity)
    for _,ep:=range cfg.Endpoints {
        identity,err:=config.NormalizeAddress(ep.Address,cfg.Transport.Scheme)
        if err!=nil { return nil,err }
        p.Endpoints=append(p.Endpoints,NewEndpointRuntime(cfg.ID,identity,ep.Address,incarnation(cfg.ID+"|"+identity),ep.Weight,ep.Zone))
    }
    return p,nil
}

func SnapshotStatus(s *RuntimeSnapshot) map[string]any {
    if s==nil { return map[string]any{"ready":false,"generation":0} }
    pools:=make([]map[string]any,0,len(s.Pools))
    for id,p:=range s.Pools {
        healthy,unhealthy,draining,inflight:=0,0,0,int64(0)
        for _,ep:=range p.Endpoints { if ep.Health()==HealthHealthy { healthy++ }; if ep.Health()==HealthUnhealthy { unhealthy++ }; if ep.Lifecycle()==LifecycleDraining { draining++ }; inflight+=ep.Inflight() }
        pools=append(pools,map[string]any{"id":id,"endpoints":len(p.Endpoints),"healthy":healthy,"unhealthy":unhealthy,"draining":draining,"inflight":inflight,"sticky_entries":p.StickyCount()})
    }
    return map[string]any{"ready":true,"generation":s.Generation,"digest":s.Digest,"created_at":s.CreatedAt.UTC().Format(time.RFC3339Nano),"references":s.References(),"routes":len(s.Routes),"pools":pools,"sources":s.SourceRevisions}
}

func ValidateSnapshot(s *RuntimeSnapshot) error {
    if s==nil { return errors.New("nil snapshot") }
    if s.Generation==0 { return errors.New("generation must be positive") }
    if len(s.Routes)==0 { return errors.New("snapshot has no routes") }
    if len(s.Pools)==0 { return errors.New("snapshot has no pools") }
    for _,r:=range s.Routes { if _,ok:=s.Pools[r.PoolID]; !ok { return fmt.Errorf("route %s references pool %s not in snapshot",r.ID,r.PoolID) } }
    return nil
}
