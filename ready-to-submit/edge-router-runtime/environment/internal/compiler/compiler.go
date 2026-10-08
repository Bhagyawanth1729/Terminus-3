package compiler

import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "fmt"
    "sort"
    "strings"
    "time"

    "edge-router-runtime/internal/config"
    rt "edge-router-runtime/internal/runtime"
)

type Compiler struct{}

func New() *Compiler { return &Compiler{} }

type Result struct {
    Desired config.Document
    Routes []*rt.CompiledRoute
    PoolConfigs map[string]config.Pool
    SourceRevisions map[string]uint64
    SourceDigests map[string]string
    Digest string
}

func (c *Compiler) Compile(input config.Document) (*Result,error) {
    normalized:=config.Normalize(input)
    if err:=config.Validate(normalized); err!=nil { return nil,err }
    pools:=make(map[string]config.Pool,len(normalized.Pools))
    for _,p:=range normalized.Pools { pools[p.ID]=p }
    routes:=make([]*rt.CompiledRoute,0,len(normalized.Routes))
    for _,r:=range normalized.Routes {
        cr,err:=compileRoute(r,pools)
        if err!=nil { return nil,err }
        routes=append(routes,cr)
    }
    sort.SliceStable(routes,func(i,j int)bool{
        if routes[i].Priority!=routes[j].Priority { return routes[i].Priority>routes[j].Priority }
        if len(routes[i].PathPrefix)!=len(routes[j].PathPrefix) { return len(routes[i].PathPrefix)>len(routes[j].PathPrefix) }
        return routes[i].ID<routes[j].ID
    })
    revs:=map[string]uint64{}
    digests:=map[string]string{}
    for _,s:=range normalized.Sources { revs[s.Name]=s.Revision; digests[s.Name]=s.Digest }
    b,_:=json.Marshal(struct{Routes []*rt.CompiledRoute; Pools map[string]config.Pool}{routes,pools})
    sum:=sha256.Sum256(b)
    return &Result{Desired:normalized,Routes:routes,PoolConfigs:pools,SourceRevisions:revs,SourceDigests:digests,Digest:hex.EncodeToString(sum[:])},nil
}

func compileRoute(r config.Route,pools map[string]config.Pool)(*rt.CompiledRoute,error){
    if _,ok:=pools[r.Pool]; !ok { return nil,fmt.Errorf("route %s references missing pool %s",r.ID,r.Pool) }
    hosts:=map[string]struct{}{}
    for _,h:=range r.Hosts { hosts[strings.ToLower(strings.TrimSuffix(h,"."))]=struct{}{} }
    methods:=map[string]struct{}{}
    for _,m:=range r.Methods { methods[strings.ToUpper(m)]=struct{}{} }
    if len(methods)==0 { methods["GET"]=struct{}{}; methods["HEAD"]=struct{}{} }
    for _,f:=range r.FailoverPools { if _,ok:=pools[f]; !ok { return nil,fmt.Errorf("route %s references missing failover %s",r.ID,f) } }
    return &rt.CompiledRoute{ID:r.ID,Hosts:hosts,PathPrefix:r.PathPrefix,Methods:methods,Headers:r.Headers,PoolID:r.Pool,Failover:append([]string(nil),r.FailoverPools...),Retry:r.Retry,Affinity:r.Affinity,Priority:r.Priority,Digest:config.RouteDigest(r)},nil
}

func RestoreFromCheckpoint(desired config.Document, serializedRoutes []*rt.CompiledRoute, pools map[string]*rt.PoolRuntime, generation uint64, digest string)(*rt.RuntimeSnapshot,error){
    if len(serializedRoutes)==0 || len(pools)==0 { return nil,fmt.Errorf("checkpoint runtime state incomplete") }
    cfgs:=map[string]config.Pool{}
    for _,p:=range desired.Pools { cfgs[p.ID]=p }
    revs:=map[string]uint64{}
    digs:=map[string]string{}
    for _,s:=range desired.Sources { revs[s.Name]=s.Revision; digs[s.Name]=s.Digest }
    return &rt.RuntimeSnapshot{Generation:generation,CreatedAt:time.Now(),Routes:serializedRoutes,Pools:pools,PoolConfigs:cfgs,SourceRevisions:revs,SourceDigests:digs,Desired:desired,Digest:digest},nil
}
