package bootstrap

import(
    "context"
    "errors"
    "fmt"
    "log"
    "os"
    "os/signal"
    "sync"
    "sync/atomic"
    "syscall"
    "time"

    "edge-router-runtime/internal/admin"
    "edge-router-runtime/internal/checkpoint"
    "edge-router-runtime/internal/compiler"
    "edge-router-runtime/internal/config"
    "edge-router-runtime/internal/drain"
    "edge-router-runtime/internal/health"
    "edge-router-runtime/internal/reconcile"
    "edge-router-runtime/internal/router"
    rt "edge-router-runtime/internal/runtime"
    "edge-router-runtime/internal/selection"
    "edge-router-runtime/internal/telemetry"
    "edge-router-runtime/internal/upstream"
)

type Options struct{ConfigPath string;StateDir string;Listen string;AdminListen string}
type Host struct{opts Options;telemetry *telemetry.Registry;store *rt.PublicationStore;checkpoints *checkpoint.Store;transport *upstream.Manager;drains *drain.Manager;compiler *compiler.Compiler;reconciler *reconcile.Reconciler;ingress *config.Ingress;health *health.Manager;selector *selection.Engine;router *router.Server;admin *admin.Server;ready atomic.Bool;cancel context.CancelFunc;wg sync.WaitGroup}
func New(opts Options)*Host{t:=telemetry.New(512);store:=rt.NewPublicationStore(12);cp:=checkpoint.New(opts.StateDir,4);tr:=upstream.New(t);dr:=drain.New(t,tr);comp:=compiler.New();rec:=reconcile.New(comp,store,cp,dr,t);ing:=config.NewIngress(rec,16);hm:=health.New(store,t);sel:=selection.New(store);rs:=router.New(opts.Listen,store,sel,tr,hm,t);h:=&Host{opts:opts,telemetry:t,store:store,checkpoints:cp,transport:tr,drains:dr,compiler:comp,reconciler:rec,ingress:ing,health:hm,selector:sel,router:rs};h.admin=admin.New(opts.AdminListen,ing,rec,store,t,h.ready.Load);return h}
func (h *Host) Start(ctx context.Context)error{ctx,h.cancel=context.WithCancel(ctx);if err:=h.checkpoints.Ensure();err!=nil{return err};h.ingress.Start(ctx);h.wg.Add(2);go func(){defer h.wg.Done();h.drains.Run(ctx)}();go func(){defer h.wg.Done();h.health.Run(ctx)}();if err:=h.recoverOrBootstrap(ctx);err!=nil{return err};h.ready.Store(true);h.wg.Add(2);errCh:=make(chan error,2);go func(){defer h.wg.Done();if err:=h.router.ListenAndServe();err!=nil{errCh<-fmt.Errorf("data plane: %w",err)}}();go func(){defer h.wg.Done();if err:=h.admin.ListenAndServe();err!=nil{errCh<-fmt.Errorf("admin plane: %w",err)}}();select{case<-ctx.Done():return nil;case err:=<-errCh:return err}}
func (h *Host) recoverOrBootstrap(ctx context.Context)error{cp,err:=h.checkpoints.LoadCurrent();if err==nil{h.startProvidersBeforeFences(ctx);snap,restoreErr:=h.restore(cp);if restoreErr==nil{h.store.Publish(snap);h.reconciler.RestoreMetadata(cp.Generation,cp.AcceptedSources);h.ingress.InstallRecovered(cp.AcceptedSources);h.telemetry.Event("recovery","recovered current checkpoint",map[string]string{"generation":fmt.Sprint(cp.Generation)});return nil};return fmt.Errorf("recover current checkpoint: %w",restoreErr)};if !errors.Is(err,os.ErrNotExist){return fmt.Errorf("read current checkpoint: %w",err)};doc,err:=config.Load(h.opts.ConfigPath);if err!=nil{return err};raw,err:=config.Encode(doc);if err!=nil{return err};revision:=doc.Generation;if revision==0{revision=1};result,err:=h.ingress.Submit(ctx,"bootstrap",revision,raw);if err!=nil{return err};if result.Outcome!="accepted"{return fmt.Errorf("bootstrap was %s: %s",result.Outcome,result.Message)};return nil}
func (h *Host) startProvidersBeforeFences(ctx context.Context){h.telemetry.Event("recovery","providers enabled",nil);_ = ctx}
func (h *Host) restore(cp checkpoint.Checkpoint)(*rt.RuntimeSnapshot,error){routes:=make([]*rt.CompiledRoute,0,len(cp.Desired.Routes));pools:=map[string]*rt.PoolRuntime{};cfgs:=map[string]config.Pool{};for _,p:=range cp.Desired.Pools{cfgs[p.ID]=p;pool,err:=rt.BuildPoolRuntime(p,nil,func(string)uint64{return 1});if err!=nil{return nil,err};pools[p.ID]=pool};compiled,err:=h.compiler.Compile(cp.Desired);if err!=nil{return nil,err};routes=compiled.Routes;return compiler.RestoreFromCheckpoint(cp.Desired,routes,pools,cp.Generation,cp.Digest)}
func (h *Host) Shutdown(ctx context.Context)error{h.ready.Store(false);if h.cancel!=nil{h.cancel()};deadline:=time.Now().Add(5*time.Second);h.drains.StopAll(deadline);aerr:=h.admin.Shutdown(ctx);rerr:=h.router.Shutdown(ctx);h.transport.Close();done:=make(chan struct{});go func(){h.wg.Wait();close(done)}();select{case<-done:case<-ctx.Done():return ctx.Err()};return errors.Join(aerr,rerr)}
func (h *Host) RunUntilSignal()error{ctx,stop:=signal.NotifyContext(context.Background(),syscall.SIGINT,syscall.SIGTERM);defer stop();errCh:=make(chan error,1);go func(){errCh<-h.Start(ctx)}();select{case err:=<-errCh:return err;case<-ctx.Done():shutdownCtx,cancel:=context.WithTimeout(context.Background(),10*time.Second);defer cancel();return h.Shutdown(shutdownCtx)}}
func (h *Host) Status()map[string]any{return map[string]any{"ready":h.ready.Load(),"runtime":rt.SnapshotStatus(h.store.Current()),"reconciler":h.reconciler.Status(),"events":h.telemetry.Recent()}}
func ValidateOnly(path string)error{doc,err:=config.Load(path);if err!=nil{return err};_,err=compiler.New().Compile(doc);return err}
func LogOptions(o Options){log.Printf("starting edge routing runtime config=%s state=%s listen=%s admin=%s",o.ConfigPath,o.StateDir,o.Listen,o.AdminListen)}
