package upstream

import(
    "context"
    "crypto/tls"
    "fmt"
    "io"
    "net"
    "net/http"
    "sync"
    "time"

    "edge-router-runtime/internal/config"
    rt "edge-router-runtime/internal/runtime"
    "edge-router-runtime/internal/telemetry"
)

type Manager struct{mu sync.Mutex;clients map[string]*http.Client;transports map[string]*http.Transport;telemetry *telemetry.Registry}
func New(t *telemetry.Registry)*Manager{return &Manager{clients:map[string]*http.Client{},transports:map[string]*http.Transport{},telemetry:t}}
func transportKey(ep *rt.EndpointRuntime,cfg config.TransportPolicy)string{return fmt.Sprintf("%s#%d|%s|%d|%d",ep.Identity,ep.Incarnation,cfg.Scheme,cfg.MaxIdleConns,cfg.MaxIdleConnsPerHost)}
func (m *Manager) Client(ep *rt.EndpointRuntime,cfg config.TransportPolicy)*http.Client{key:=transportKey(ep,cfg);m.mu.Lock();defer m.mu.Unlock();if c:=m.clients[key];c!=nil{return c};dialer:=&net.Dialer{Timeout:3*time.Second,KeepAlive:30*time.Second};tr:=&http.Transport{Proxy:http.ProxyFromEnvironment,DialContext:dialer.DialContext,ForceAttemptHTTP2:false,MaxIdleConns:max(cfg.MaxIdleConns,64),MaxIdleConnsPerHost:max(cfg.MaxIdleConnsPerHost,8),IdleConnTimeout:time.Duration(max(cfg.IdleConnTimeoutMS,30000))*time.Millisecond,TLSClientConfig:&tls.Config{InsecureSkipVerify:cfg.TLSInsecureSkipVerify}};c:=&http.Client{Transport:tr};m.clients[key]=c;m.transports[key]=tr;m.telemetry.Gauge("edge_transport_clients",nil).Set(int64(len(m.clients)));return c}
func (m *Manager) Do(ctx context.Context,ep *rt.EndpointRuntime,pool config.Pool,method,path string,header http.Header,body io.Reader,timeout time.Duration)(*http.Response,error){if !ep.Begin(){return nil,fmt.Errorf("endpoint retired")};defer ep.End();scheme:=pool.Transport.Scheme;if scheme==""{scheme="http"};url:=scheme+"://"+ep.Address+path;req,err:=http.NewRequestWithContext(ctx,method,url,body);if err!=nil{return nil,err};req.Header=header.Clone();client:=m.Client(ep,pool.Transport);if timeout>0{timer:=time.AfterFunc(timeout,func(){}) ;defer timer.Stop()};start:=time.Now();resp,err:=client.Do(req);elapsed:=time.Since(start);m.telemetry.Counter("edge_upstream_attempt_total",map[string]string{"pool":ep.PoolID}).Inc();m.telemetry.Gauge("edge_upstream_last_latency_ms",map[string]string{"pool":ep.PoolID}).Set(elapsed.Milliseconds());if err!=nil{m.telemetry.Counter("edge_upstream_error_total",map[string]string{"pool":ep.PoolID}).Inc()};return resp,err}
func (m *Manager) Retire(ep *rt.EndpointRuntime){m.mu.Lock();defer m.mu.Unlock();for key,tr:=range m.transports{if len(key)>=len(ep.Identity)&&key[:len(ep.Identity)]==ep.Identity{tr.CloseIdleConnections();delete(m.transports,key);delete(m.clients,key)}};m.telemetry.Gauge("edge_transport_clients",nil).Set(int64(len(m.clients)))}
func (m *Manager) Close(){m.mu.Lock();defer m.mu.Unlock();for _,tr:=range m.transports{tr.CloseIdleConnections()};m.transports=map[string]*http.Transport{};m.clients=map[string]*http.Client{}}
