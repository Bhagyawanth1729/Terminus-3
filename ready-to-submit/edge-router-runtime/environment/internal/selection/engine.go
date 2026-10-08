package selection

import (
    "errors"
    "fmt"
    "hash/fnv"
    "net/http"
    "sort"
    "strings"
    "time"

    "edge-router-runtime/internal/config"
    rt "edge-router-runtime/internal/runtime"
)

var ErrNoEligible = errors.New("no eligible upstream endpoint")

type GlobalPools interface { GlobalPool(string)(*rt.PoolRuntime,bool) }

type Engine struct { global GlobalPools }
func New(global GlobalPools)*Engine{ return &Engine{global:global} }

type AttemptState struct { Used map[*rt.EndpointRuntime]struct{}; Attempts int }
func NewAttemptState()*AttemptState{ return &AttemptState{Used:map[*rt.EndpointRuntime]struct{}{}} }

type Choice struct { PoolID string; Endpoint *rt.EndpointRuntime; Sticky bool; Failover bool }

func (e *Engine) Choose(req *http.Request,snapshot *rt.RuntimeSnapshot,route *rt.CompiledRoute,state *AttemptState)(Choice,error){
    if snapshot==nil||route==nil { return Choice{},ErrNoEligible }
    chain:=append([]string{route.PoolID},route.Failover...)
    for i,poolID:=range chain {
        var pool *rt.PoolRuntime
        var ok bool
        if i==0 { pool,ok=snapshot.Pool(poolID) } else { pool,ok=e.global.GlobalPool(poolID) }
        if !ok { continue }
        key:=affinityKey(req,route.Affinity)
        if key!="" {
            if entry,exists:=pool.Sticky(key); exists && (entry.ExpiresAt.IsZero()||time.Now().Before(entry.ExpiresAt)) {
                for _,ep:=range pool.Endpoints {
                    if ep.Identity==entry.EndpointIdentity {
                        if _,used:=state.Used[ep]; !used { state.Used[ep]=struct{}{}; state.Attempts++; return Choice{PoolID:poolID,Endpoint:ep,Sticky:true,Failover:i>0},nil }
                    }
                }
            }
        }
        ep:=e.choosePool(pool,state)
        if ep!=nil {
            state.Used[ep]=struct{}{}
            state.Attempts++
            if key!="" { ttl:=route.Affinity.TTLSeconds; if ttl<=0 { ttl=300 }; cap:=route.Affinity.Capacity; if cap<=0 { cap=4096 }; pool.PutSticky(key,rt.StickyEntry{EndpointIdentity:ep.Identity,Incarnation:ep.Incarnation,ExpiresAt:time.Now().Add(time.Duration(ttl)*time.Second),LastUsed:time.Now()},cap) }
            return Choice{PoolID:poolID,Endpoint:ep,Failover:i>0},nil
        }
    }
    for _,poolID:=range chain {
        pool,ok:=e.global.GlobalPool(poolID)
        if !ok { continue }
        for _,ep:=range pool.Endpoints { if _,used:=state.Used[ep]; !used { state.Used[ep]=struct{}{}; return Choice{PoolID:poolID,Endpoint:ep},nil } }
    }
    return Choice{},ErrNoEligible
}

func (e *Engine) choosePool(pool *rt.PoolRuntime,state *AttemptState)*rt.EndpointRuntime{
    eligible:=make([]*rt.EndpointRuntime,0,len(pool.Endpoints))
    for _,ep:=range pool.Endpoints {
        if _,used:=state.Used[ep]; used { continue }
        if ep.Health()==rt.HealthUnhealthy { continue }
        eligible=append(eligible,ep)
    }
    if len(eligible)==0 { return nil }
    switch pool.Strategy {
    case "least_inflight":
        sort.SliceStable(eligible,func(i,j int)bool{ if eligible[i].Inflight()!=eligible[j].Inflight(){return eligible[i].Inflight()<eligible[j].Inflight()}; return eligible[i].Identity<eligible[j].Identity })
        return eligible[0]
    case "weighted":
        total:=0
        for _,ep:=range eligible { total+=max(ep.Weight,1) }
        n:=pool.NextIndex(total)
        if n<0 { return nil }
        for _,ep:=range eligible { n-=max(ep.Weight,1); if n<0 { return ep } }
        return eligible[len(eligible)-1]
    default:
        return eligible[pool.NextIndex(len(eligible))]
    }
}

func affinityKey(req *http.Request,a config.AffinityPolicy)string{
    switch a.Mode {
    case "header": return strings.TrimSpace(req.Header.Get(a.Header))
    case "cookie": if c,err:=req.Cookie(a.Cookie);err==nil{return c.Value}
    }
    return ""
}

func HashKey(s string)uint64{ h:=fnv.New64a();_,_=h.Write([]byte(s));return h.Sum64() }
func IsRetryable(status int,err error,policy config.RetryPolicy)bool{ if err!=nil{return contains(policy.RetryOn,"connect-error")||contains(policy.RetryOn,"reset")}; if status>=500{return contains(policy.RetryOn,"5xx")}; return status==429&&contains(policy.RetryOn,"429") }
func contains(items []string,want string)bool{ for _,v:=range items{if strings.EqualFold(v,want){return true}};return false }
func Describe(c Choice)string{ if c.Endpoint==nil{return "none"};return fmt.Sprintf("%s/%s#%d",c.PoolID,c.Endpoint.Identity,c.Endpoint.Incarnation) }
