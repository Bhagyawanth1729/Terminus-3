package config

import(
    "context"
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "sync"
    "time"
)

type SubmitResult struct{Source string `json:"source"`;Revision uint64 `json:"revision"`;Digest string `json:"digest"`;Outcome string `json:"outcome"`;Message string `json:"message,omitempty"`}
type Processor interface{Process(context.Context,Candidate)SubmitResult}
type Envelope struct{Source string;Revision uint64;Raw []byte;Reply chan SubmitResult}

type Ingress struct{processor Processor;queue chan Envelope;mu sync.Mutex;lastRevision uint64;cached map[string]Document;cachedRevision map[string]uint64;cachedDigest map[string]string;started bool}
func NewIngress(p Processor,capacity int)*Ingress{if capacity<2{capacity=8};return &Ingress{processor:p,queue:make(chan Envelope,capacity),cached:map[string]Document{},cachedRevision:map[string]uint64{},cachedDigest:map[string]string{}}}
func (i *Ingress) Start(ctx context.Context){i.mu.Lock();if i.started{i.mu.Unlock();return};i.started=true;i.mu.Unlock();go i.loop(ctx)}
func (i *Ingress) Submit(ctx context.Context,source string,revision uint64,raw []byte)(SubmitResult,error){if source==""{return SubmitResult{},errors.New("source required")};reply:=make(chan SubmitResult,1);env:=Envelope{Source:source,Revision:revision,Raw:append([]byte(nil),raw...),Reply:reply};select{case i.queue<-env:case<-ctx.Done():return SubmitResult{},ctx.Err();default:select{case old:=<-i.queue:i.queue<-old;default:};select{case i.queue<-env:default:return SubmitResult{Source:source,Revision:revision,Outcome:"coalesced",Message:"queue retained an earlier complete snapshot"},nil}};select{case r:=<-reply:return r,nil;case<-ctx.Done():return SubmitResult{},ctx.Err()}}
func (i *Ingress) loop(ctx context.Context){for{select{case<-ctx.Done():return;case env:=<-i.queue:i.handle(ctx,env)}}}
func (i *Ingress) handle(ctx context.Context,env Envelope){sum:=sha256.Sum256(env.Raw);digest:=hex.EncodeToString(sum[:]);i.mu.Lock();if env.Revision<i.lastRevision{i.mu.Unlock();env.Reply<-SubmitResult{Source:env.Source,Revision:env.Revision,Digest:digest,Outcome:"stale",Message:"revision below accepted fence"};return};var doc Document;if err:=json.Unmarshal(env.Raw,&doc);err!=nil{i.mu.Unlock();env.Reply<-SubmitResult{Source:env.Source,Revision:env.Revision,Digest:digest,Outcome:"rejected",Message:err.Error()};return};i.lastRevision=env.Revision;i.cached[env.Source]=doc;i.cachedRevision[env.Source]=env.Revision;i.cachedDigest[env.Source]=digest;merged:=i.mergeLocked();i.mu.Unlock();candidate:=Candidate{Source:env.Source,Revision:env.Revision,Digest:digest,Document:merged,ReceivedAt:time.Now()};env.Reply<-i.processor.Process(ctx,candidate)}
func (i *Ingress) mergeLocked()Document{var out Document;first:=true;for _,doc:=range i.cached{if first{out=doc;first=false}else{out=Merge(out,doc)}};out.Sources=out.Sources[:0];for name,rev:=range i.cachedRevision{out.Sources=append(out.Sources,SourceState{Name:name,Revision:rev,Digest:i.cachedDigest[name]})};return out}
func (i *Ingress) AcceptedSources()[]SourceState{i.mu.Lock();defer i.mu.Unlock();out:=make([]SourceState,0,len(i.cachedRevision));for name,rev:=range i.cachedRevision{out=append(out,SourceState{Name:name,Revision:rev,Digest:i.cachedDigest[name]})};return out}
func (i *Ingress) InstallRecovered(sources []SourceState){i.mu.Lock();defer i.mu.Unlock();for _,s:=range sources{i.cachedRevision[s.Name]=s.Revision;i.cachedDigest[s.Name]=s.Digest;if s.Revision>i.lastRevision{i.lastRevision=s.Revision}}}
func (i *Ingress) LoadBootstrap(path string)(Document,error){doc,err:=Load(path);if err!=nil{return Document{},fmt.Errorf("bootstrap: %w",err)};return doc,nil}
