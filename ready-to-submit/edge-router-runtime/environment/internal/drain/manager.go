package drain

import(
    "context"
    "sync"
    "time"

    rt "edge-router-runtime/internal/runtime"
    "edge-router-runtime/internal/telemetry"
)

type TransportRetirer interface{Retire(*rt.EndpointRuntime)}
type Manager struct{mu sync.Mutex;items map[string]*rt.EndpointRuntime;telemetry *telemetry.Registry;transport TransportRetirer;interval time.Duration}
func New(t *telemetry.Registry,tr TransportRetirer)*Manager{return &Manager{items:map[string]*rt.EndpointRuntime{},telemetry:t,transport:tr,interval:100*time.Millisecond}}
func key(ep *rt.EndpointRuntime)string{return ep.PoolID+"|"+ep.Identity+"#"+string(rune(ep.Incarnation))}
func (m *Manager) Start(ep *rt.EndpointRuntime,deadline time.Time){if ep==nil{return};ep.StartDrain(deadline);m.mu.Lock();m.items[key(ep)]=ep;m.mu.Unlock();m.telemetry.Counter("edge_drain_started_total",map[string]string{"pool":ep.PoolID}).Inc();m.telemetry.Event("drain","endpoint entered draining state",map[string]string{"pool":ep.PoolID,"endpoint":ep.Identity})}
func (m *Manager) Pending()int{m.mu.Lock();defer m.mu.Unlock();return len(m.items)}
func (m *Manager) Run(ctx context.Context){ticker:=time.NewTicker(m.interval);defer ticker.Stop();for{select{case<-ctx.Done():return;case now:=<-ticker.C:m.sweep(now)}}}
func (m *Manager) sweep(now time.Time){m.mu.Lock();defer m.mu.Unlock();for k,ep:=range m.items{deadline:=ep.DrainDeadline();done:=ep.Inflight()==0;if !deadline.IsZero()&&now.After(deadline){done=true};if !done{continue};ep.Retire();if m.transport!=nil{m.transport.Retire(ep)};delete(m.items,k);m.telemetry.Counter("edge_drain_completed_total",map[string]string{"pool":ep.PoolID}).Inc();m.telemetry.Event("drain","endpoint retired",map[string]string{"pool":ep.PoolID,"endpoint":ep.Identity})}}
func (m *Manager) StopAll(deadline time.Time){m.mu.Lock();defer m.mu.Unlock();for _,ep:=range m.items{ep.StartDrain(deadline)}}
