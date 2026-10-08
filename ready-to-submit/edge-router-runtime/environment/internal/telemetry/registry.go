package telemetry

import (
    "fmt"
    "io"
    "sort"
    "strconv"
    "strings"
    "sync"
    "sync/atomic"
    "time"
)

type Counter struct{ value atomic.Uint64 }
func (c *Counter) Inc(){c.value.Add(1)}
func (c *Counter) Add(v uint64){c.value.Add(v)}
func (c *Counter) Value()uint64{return c.value.Load()}

type Gauge struct{ bits atomic.Int64 }
func (g *Gauge) Set(v int64){g.bits.Store(v)}
func (g *Gauge) Add(v int64){g.bits.Add(v)}
func (g *Gauge) Value()int64{return g.bits.Load()}

type metricKey struct{Name string; Labels string}
type Scope struct{ Kind string; ID string; Created time.Time }

type Registry struct{
    mu sync.RWMutex
    counters map[metricKey]*Counter
    gauges map[metricKey]*Gauge
    scopes map[string]Scope
    recent []Event
    recentLimit int
}

type Event struct{At time.Time `json:"at"`; Kind string `json:"kind"`; Message string `json:"message"`; Fields map[string]string `json:"fields,omitempty"`}

func New(limit int)*Registry{if limit<32{limit=256};return &Registry{counters:map[metricKey]*Counter{},gauges:map[metricKey]*Gauge{},scopes:map[string]Scope{},recentLimit:limit}}

func labels(values map[string]string)string{
    if len(values)==0{return ""}
    keys:=make([]string,0,len(values));for k:=range values{keys=append(keys,k)};sort.Strings(keys)
    parts:=make([]string,0,len(keys));for _,k:=range keys{parts=append(parts,k+"="+values[k])};return strings.Join(parts,",")
}

func (r *Registry) Counter(name string,l map[string]string)*Counter{key:=metricKey{name,labels(l)};r.mu.RLock();v:=r.counters[key];r.mu.RUnlock();if v!=nil{return v};r.mu.Lock();defer r.mu.Unlock();if v=r.counters[key];v==nil{v=&Counter{};r.counters[key]=v};return v}
func (r *Registry) Gauge(name string,l map[string]string)*Gauge{key:=metricKey{name,labels(l)};r.mu.RLock();v:=r.gauges[key];r.mu.RUnlock();if v!=nil{return v};r.mu.Lock();defer r.mu.Unlock();if v=r.gauges[key];v==nil{v=&Gauge{};r.gauges[key]=v};return v}
func (r *Registry) RegisterScope(kind,id string){r.mu.Lock();r.scopes[kind+":"+id]=Scope{Kind:kind,ID:id,Created:time.Now()};r.mu.Unlock()}
func (r *Registry) UnregisterScope(kind,id string){r.mu.Lock();_ = kind;_ = id;r.mu.Unlock()}
func (r *Registry) ScopeCount()int{r.mu.RLock();defer r.mu.RUnlock();return len(r.scopes)}
func (r *Registry) Event(kind,message string,fields map[string]string){r.mu.Lock();r.recent=append(r.recent,Event{At:time.Now(),Kind:kind,Message:message,Fields:fields});if len(r.recent)>r.recentLimit{r.recent=r.recent[len(r.recent)-r.recentLimit:]};r.mu.Unlock()}
func (r *Registry) Recent()[]Event{r.mu.RLock();defer r.mu.RUnlock();out:=make([]Event,len(r.recent));copy(out,r.recent);return out}

func (r *Registry) WritePrometheus(w io.Writer){
    r.mu.RLock();defer r.mu.RUnlock()
    ckeys:=make([]metricKey,0,len(r.counters));for k:=range r.counters{ckeys=append(ckeys,k)};sort.Slice(ckeys,func(i,j int)bool{if ckeys[i].Name!=ckeys[j].Name{return ckeys[i].Name<ckeys[j].Name};return ckeys[i].Labels<ckeys[j].Labels})
    for _,k:=range ckeys{fmt.Fprintf(w,"%s%s %d\n",sanitize(k.Name),promLabels(k.Labels),r.counters[k].Value())}
    gkeys:=make([]metricKey,0,len(r.gauges));for k:=range r.gauges{gkeys=append(gkeys,k)};sort.Slice(gkeys,func(i,j int)bool{if gkeys[i].Name!=gkeys[j].Name{return gkeys[i].Name<gkeys[j].Name};return gkeys[i].Labels<gkeys[j].Labels})
    for _,k:=range gkeys{fmt.Fprintf(w,"%s%s %d\n",sanitize(k.Name),promLabels(k.Labels),r.gauges[k].Value())}
}

func sanitize(v string)string{var b strings.Builder;for i,r:=range v{if (r>='a'&&r<='z')||(r>='A'&&r<='Z')||r=='_'||(i>0&&r>='0'&&r<='9'){b.WriteRune(r)}else{b.WriteByte('_')}};return b.String()}
func promLabels(v string)string{if v==""{return ""};pairs:=strings.Split(v,",");out:=make([]string,0,len(pairs));for _,p:=range pairs{kv:=strings.SplitN(p,"=",2);if len(kv)==2{out=append(out,sanitize(kv[0])+"="+strconv.Quote(kv[1]))}};return "{"+strings.Join(out,",")+"}"}
