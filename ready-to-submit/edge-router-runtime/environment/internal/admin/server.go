package admin

import(
    "context"
    "encoding/json"
    "errors"
    "io"
    "net/http"
    "strconv"
    "strings"
    "time"

    "edge-router-runtime/internal/config"
    "edge-router-runtime/internal/reconcile"
    rt "edge-router-runtime/internal/runtime"
    "edge-router-runtime/internal/telemetry"
)

type Server struct{addr string;ingress *config.Ingress;reconciler *reconcile.Reconciler;store *rt.PublicationStore;telemetry *telemetry.Registry;server *http.Server;ready func()bool}
func New(addr string,ing *config.Ingress,rec *reconcile.Reconciler,store *rt.PublicationStore,t *telemetry.Registry,ready func()bool)*Server{s:=&Server{addr:addr,ingress:ing,reconciler:rec,store:store,telemetry:t,ready:ready};mux:=http.NewServeMux();mux.HandleFunc("/v1/config",s.handleConfig);mux.HandleFunc("/v1/discovery",s.handleDiscovery);mux.HandleFunc("/v1/status",s.handleStatus);mux.HandleFunc("/ready",s.handleReady);mux.HandleFunc("/health",s.handleHealth);mux.HandleFunc("/metrics",s.handleMetrics);mux.HandleFunc("/v1/events",s.handleEvents);s.server=&http.Server{Addr:addr,Handler:mux,ReadHeaderTimeout:5*time.Second,IdleTimeout:30*time.Second};return s}
func (s *Server) ListenAndServe()error{err:=s.server.ListenAndServe();if errors.Is(err,http.ErrServerClosed){return nil};return err}
func (s *Server) Shutdown(ctx context.Context)error{return s.server.Shutdown(ctx)}
func (s *Server) handleConfig(w http.ResponseWriter,r *http.Request){s.handleSubmit(w,r,"config")}
func (s *Server) handleDiscovery(w http.ResponseWriter,r *http.Request){s.handleSubmit(w,r,"discovery")}
func (s *Server) handleSubmit(w http.ResponseWriter,r *http.Request,defaultSource string){if r.Method!=http.MethodPost{http.Error(w,"method not allowed",http.StatusMethodNotAllowed);return};source:=strings.TrimSpace(r.URL.Query().Get("source"));if source==""{source=defaultSource};revision,err:=strconv.ParseUint(r.URL.Query().Get("revision"),10,64);if err!=nil||revision==0{http.Error(w,"revision query parameter must be positive",http.StatusBadRequest);return};raw,err:=io.ReadAll(io.LimitReader(r.Body,8<<20));if err!=nil{http.Error(w,err.Error(),http.StatusBadRequest);return};ctx,cancel:=context.WithTimeout(r.Context(),15*time.Second);defer cancel();result,err:=s.ingress.Submit(ctx,source,revision,raw);if err!=nil{http.Error(w,err.Error(),http.StatusServiceUnavailable);return};status:=http.StatusOK;if result.Outcome=="rejected"||result.Outcome=="stale"{status=http.StatusConflict};writeJSON(w,status,result)}
func (s *Server) handleStatus(w http.ResponseWriter,r *http.Request){if r.Method!=http.MethodGet{http.Error(w,"method not allowed",http.StatusMethodNotAllowed);return};writeJSON(w,http.StatusOK,map[string]any{"runtime":rt.SnapshotStatus(s.store.Current()),"reconciler":s.reconciler.Status(),"metric_scopes":s.telemetry.ScopeCount()})}
func (s *Server) handleReady(w http.ResponseWriter,r *http.Request){if s.ready!=nil&&!s.ready(){writeJSON(w,http.StatusServiceUnavailable,map[string]any{"ready":false});return};if s.store.Current()==nil{writeJSON(w,http.StatusServiceUnavailable,map[string]any{"ready":false});return};writeJSON(w,http.StatusOK,map[string]any{"ready":true,"generation":s.store.Generation()})}
func (s *Server) handleHealth(w http.ResponseWriter,r *http.Request){writeJSON(w,http.StatusOK,map[string]any{"ok":true})}
func (s *Server) handleMetrics(w http.ResponseWriter,r *http.Request){w.Header().Set("Content-Type","text/plain; version=0.0.4");s.telemetry.WritePrometheus(w)}
func (s *Server) handleEvents(w http.ResponseWriter,r *http.Request){writeJSON(w,http.StatusOK,map[string]any{"events":s.telemetry.Recent()})}
func writeJSON(w http.ResponseWriter,status int,v any){w.Header().Set("Content-Type","application/json");w.WriteHeader(status);_ = json.NewEncoder(w).Encode(v)}
