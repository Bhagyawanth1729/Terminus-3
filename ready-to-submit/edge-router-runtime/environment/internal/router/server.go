package router

import(
    "context"
    "encoding/json"
    "errors"
    "io"
    "net/http"
    "strings"
    "time"

    "edge-router-runtime/internal/health"
    rt "edge-router-runtime/internal/runtime"
    "edge-router-runtime/internal/selection"
    "edge-router-runtime/internal/telemetry"
    "edge-router-runtime/internal/upstream"
)

type Server struct{store *rt.PublicationStore;selector *selection.Engine;transport *upstream.Manager;health *health.Manager;telemetry *telemetry.Registry;server *http.Server}
func New(addr string,store *rt.PublicationStore,sel *selection.Engine,tr *upstream.Manager,h *health.Manager,t *telemetry.Registry)*Server{s:=&Server{store:store,selector:sel,transport:tr,health:h,telemetry:t};s.server=&http.Server{Addr:addr,Handler:s,ReadHeaderTimeout:10*time.Second,IdleTimeout:90*time.Second};return s}
func (s *Server) ListenAndServe()error{err:=s.server.ListenAndServe();if errors.Is(err,http.ErrServerClosed){return nil};return err}
func (s *Server) Shutdown(ctx context.Context)error{return s.server.Shutdown(ctx)}
func (s *Server) ServeHTTP(w http.ResponseWriter,r *http.Request){start:=time.Now();s.telemetry.Counter("edge_requests_total",map[string]string{"method":r.Method}).Inc();snap:=s.store.Acquire();if snap==nil{http.Error(w,"router not ready",http.StatusServiceUnavailable);return};route:=matchRoute(snap.Routes,r);snap.Release();if route==nil{http.NotFound(w,r);return};state:=selection.NewAttemptState();attempts:=max(route.Retry.Attempts,1);var lastErr error;for attempt:=0;attempt<attempts;attempt++{lease:=s.store.Acquire();if lease==nil{lastErr=errors.New("snapshot unavailable");break};choice,err:=s.selector.Choose(r,lease,route,state);lease.Release();if err!=nil{lastErr=err;break};poolCfg,ok:=s.store.GlobalPoolConfig(choice.PoolID);if !ok{lastErr=errors.New("pool disappeared");continue};timeout:=time.Duration(max(route.Retry.PerTryTimeoutMS,1000))*time.Millisecond;resp,err:=s.transport.Do(r.Context(),choice.Endpoint,poolCfg,r.Method,r.URL.RequestURI(),r.Header,r.Body,timeout);status:=0;if resp!=nil{status=resp.StatusCode};s.health.Passive(choice.Endpoint,status,err,poolCfg.Health.UnhealthyThreshold);if !selection.IsRetryable(status,err,route.Retry){if err!=nil{lastErr=err;break};copyResponse(w,resp);s.telemetry.Gauge("edge_request_last_duration_ms",nil).Set(time.Since(start).Milliseconds());return};if resp!=nil{io.Copy(io.Discard,resp.Body);resp.Body.Close()};lastErr=err};s.telemetry.Counter("edge_request_failures_total",nil).Inc();if lastErr!=nil{http.Error(w,"upstream unavailable: "+lastErr.Error(),http.StatusServiceUnavailable)}else{http.Error(w,"upstream unavailable",http.StatusServiceUnavailable)}}
func matchRoute(routes []*rt.CompiledRoute,r *http.Request)*rt.CompiledRoute{host:=strings.ToLower(strings.Split(r.Host,":")[0]);for _,route:=range routes{if _,ok:=route.Methods[r.Method];!ok{continue};if len(route.Hosts)>0{if _,all:=route.Hosts["*"];!all{if _,ok:=route.Hosts[host];!ok{continue}}};if !strings.HasPrefix(r.URL.Path,route.PathPrefix){continue};matched:=true;for _,h:=range route.Headers{v:=r.Header.Get(h.Name);if h.Exact!=""&&v!=h.Exact{matched=false;break};if h.Prefix!=""&&!strings.HasPrefix(v,h.Prefix){matched=false;break}};if matched{return route}};return nil}
func copyResponse(w http.ResponseWriter,resp *http.Response){defer resp.Body.Close();for k,values:=range resp.Header{if hopByHop(k){continue};for _,v:=range values{w.Header().Add(k,v)}};w.WriteHeader(resp.StatusCode);_,_=io.Copy(w,resp.Body)}
func hopByHop(k string)bool{switch strings.ToLower(k){case "connection","proxy-connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade":return true};return false}
func JSONError(w http.ResponseWriter,status int,message string){w.Header().Set("Content-Type","application/json");w.WriteHeader(status);_ = json.NewEncoder(w).Encode(map[string]any{"error":message,"status":status})}
