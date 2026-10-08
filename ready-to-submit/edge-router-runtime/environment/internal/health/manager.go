package health

import(
    "context"
    "fmt"
    "net/http"
    "sync"
    "time"

    "edge-router-runtime/internal/config"
    rt "edge-router-runtime/internal/runtime"
    "edge-router-runtime/internal/telemetry"
)

type Provider interface{Current()*rt.RuntimeSnapshot}
type Manager struct{provider Provider;telemetry *telemetry.Registry;mu sync.Mutex;cancel map[string]context.CancelFunc}
func New(p Provider,t *telemetry.Registry)*Manager{return &Manager{provider:p,telemetry:t,cancel:map[string]context.CancelFunc{}}}
func (m *Manager) Run(ctx context.Context){ticker:=time.NewTicker(250*time.Millisecond);defer ticker.Stop();for{select{case<-ctx.Done():m.stopAll();return;case<-ticker.C:m.sync(ctx)}}}
func (m *Manager) sync(parent context.Context){s:=m.provider.Current();if s==nil{return};wanted:=map[string]struct{}{};for poolID,pool:=range s.Pools{cfg:=s.PoolConfigs[poolID];for _,ep:=range pool.Endpoints{k:=fmt.Sprintf("%s/%s#%d",poolID,ep.Identity,ep.Incarnation);wanted[k]=struct{}{};m.mu.Lock();_,exists:=m.cancel[k];if !exists{ctx,cancel:=context.WithCancel(parent);m.cancel[k]=cancel;go m.probeLoop(ctx,ep,cfg)};m.mu.Unlock()}};m.mu.Lock();for k,cancel:=range m.cancel{if _,ok:=wanted[k];!ok{cancel();delete(m.cancel,k)}};m.mu.Unlock()}
func (m *Manager) probeLoop(ctx context.Context,ep *rt.EndpointRuntime,pool config.Pool){interval:=time.Duration(max(pool.Health.IntervalMS,1000))*time.Millisecond;ticker:=time.NewTicker(interval);defer ticker.Stop();m.probe(ctx,ep,pool);for{select{case<-ctx.Done():return;case<-ticker.C:m.probe(ctx,ep,pool)}}}
func (m *Manager) probe(ctx context.Context,ep *rt.EndpointRuntime,pool config.Pool){timeout:=time.Duration(max(pool.Health.TimeoutMS,250))*time.Millisecond;pctx,cancel:=context.WithTimeout(ctx,timeout);defer cancel();scheme:=pool.Transport.Scheme;if scheme==""{scheme="http"};req,err:=http.NewRequestWithContext(pctx,http.MethodGet,scheme+"://"+ep.Address+pool.Health.Path,nil);if err!=nil{ep.MarkFailure(pool.Health.UnhealthyThreshold);return};resp,err:=http.DefaultClient.Do(req);if err!=nil{ep.MarkFailure(pool.Health.UnhealthyThreshold);m.telemetry.Counter("edge_health_failure_total",map[string]string{"pool":pool.ID}).Inc();return};resp.Body.Close();good:=false;for _,code:=range pool.Health.ExpectedStatuses{if resp.StatusCode==code{good=true;break}};if len(pool.Health.ExpectedStatuses)==0{good=resp.StatusCode>=200&&resp.StatusCode<400};if good{ep.MarkHealthy();m.telemetry.Counter("edge_health_success_total",map[string]string{"pool":pool.ID}).Inc()}else{ep.MarkFailure(pool.Health.UnhealthyThreshold);m.telemetry.Counter("edge_health_failure_total",map[string]string{"pool":pool.ID}).Inc()}}
func (m *Manager) Passive(ep *rt.EndpointRuntime,status int,err error,threshold int){if ep==nil{return};if err!=nil||status>=500{ep.MarkFailure(max(threshold,1));return};ep.MarkHealthy()}
func (m *Manager) stopAll(){m.mu.Lock();defer m.mu.Unlock();for _,c:=range m.cancel{c()};m.cancel=map[string]context.CancelFunc{}}
