package checkpoint

import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "os"
    "path/filepath"
    "sort"
    "strconv"
    "strings"
    "sync"
    "time"

    "edge-router-runtime/internal/config"
)

const SchemaVersion=1

type StickyRecord struct{PoolID string `json:"pool_id"`;Key string `json:"key"`;EndpointIdentity string `json:"endpoint_identity"`;Incarnation uint64 `json:"incarnation"`;ExpiresAt time.Time `json:"expires_at"`}
type Checkpoint struct{SchemaVersion int `json:"schema_version"`;Generation uint64 `json:"generation"`;AcceptedSources []config.SourceState `json:"accepted_sources"`;Desired config.Document `json:"desired"`;Digest string `json:"digest"`;Sticky []StickyRecord `json:"sticky,omitempty"`;CreatedAt time.Time `json:"created_at"`;Checksum string `json:"checksum"`}
type Pointer struct{Generation uint64 `json:"generation"`;File string `json:"file"`;Checksum string `json:"checksum"`}

type Store struct{dir string;mu sync.Mutex;retain int}
func New(dir string,retain int)*Store{if retain<2{retain=3};return &Store{dir:dir,retain:retain}}
func (s *Store) Dir()string{return s.dir}
func (s *Store) Ensure()error{return os.MkdirAll(s.dir,0o755)}
func bodyName(g uint64)string{return fmt.Sprintf("generation-%020d.json",g)}
func tempName(g uint64)string{return fmt.Sprintf(".generation-%020d.tmp",g)}

func (s *Store) Prepare(cp Checkpoint)(string,error){
    s.mu.Lock();defer s.mu.Unlock();if err:=s.Ensure();err!=nil{return "",err}
    cp.SchemaVersion=SchemaVersion;cp.CreatedAt=time.Now().UTC();cp.Checksum="";raw,err:=json.MarshalIndent(cp,"","  ");if err!=nil{return "",err};sum:=sha256.Sum256(raw);cp.Checksum=hex.EncodeToString(sum[:]);raw,err=json.MarshalIndent(cp,"","  ");if err!=nil{return "",err}
    tmp:=filepath.Join(s.dir,tempName(cp.Generation));final:=filepath.Join(s.dir,bodyName(cp.Generation))
    f,err:=os.OpenFile(tmp,os.O_CREATE|os.O_TRUNC|os.O_WRONLY,0o644);if err!=nil{return "",err}
    if _,err=f.Write(raw);err!=nil{f.Close();return "",err}
    if err=f.Close();err!=nil{return "",err}
    ptr:=Pointer{Generation:cp.Generation,File:filepath.Base(final),Checksum:cp.Checksum}
    if err=s.writeCurrent(ptr);err!=nil{return "",err}
    f,err=os.OpenFile(tmp,os.O_RDWR,0);if err!=nil{return "",err};if err=f.Sync();err!=nil{f.Close();return "",err};if err=f.Close();err!=nil{return "",err}
    if err=os.Rename(tmp,final);err!=nil{return "",err}
    return final,nil
}

func (s *Store) Commit(g uint64)error{s.mu.Lock();defer s.mu.Unlock();return s.pruneLocked(g)}
func (s *Store) writeCurrent(p Pointer)error{raw,_:=json.MarshalIndent(p,"","  ");tmp:=filepath.Join(s.dir,".CURRENT.tmp");if err:=os.WriteFile(tmp,raw,0o644);err!=nil{return err};return os.Rename(tmp,filepath.Join(s.dir,"CURRENT"))}
func (s *Store) fsyncDir()error{d,err:=os.Open(s.dir);if err!=nil{return err};defer d.Close();return d.Sync()}

func (s *Store) LoadCurrent()(Checkpoint,error){
    s.mu.Lock();defer s.mu.Unlock();raw,err:=os.ReadFile(filepath.Join(s.dir,"CURRENT"));if err!=nil{return Checkpoint{},err};var ptr Pointer;if err=json.Unmarshal(raw,&ptr);err!=nil{return Checkpoint{},err};body,err:=os.ReadFile(filepath.Join(s.dir,ptr.File));if err!=nil{return Checkpoint{},err};var cp Checkpoint;if err=json.Unmarshal(body,&cp);err!=nil{return Checkpoint{},err};if cp.Generation!=ptr.Generation{return Checkpoint{},fmt.Errorf("checkpoint generation mismatch")};return cp,nil
}

func (s *Store) LoadPrevious()(Checkpoint,error){
    s.mu.Lock();defer s.mu.Unlock();entries,err:=os.ReadDir(s.dir);if err!=nil{return Checkpoint{},err};var files []string;for _,e:=range entries{if !e.IsDir()&&strings.HasPrefix(e.Name(),"generation-")&&strings.HasSuffix(e.Name(),".json"){files=append(files,e.Name())}};sort.Sort(sort.Reverse(sort.StringSlice(files)));if len(files)<2{return Checkpoint{},errors.New("no previous checkpoint")};return s.readBody(files[1])
}

func (s *Store) readBody(name string)(Checkpoint,error){raw,err:=os.ReadFile(filepath.Join(s.dir,name));if err!=nil{return Checkpoint{},err};var cp Checkpoint;if err=json.Unmarshal(raw,&cp);err!=nil{return Checkpoint{},err};return cp,nil}
func (s *Store) Verify(cp Checkpoint)error{if cp.SchemaVersion!=SchemaVersion{return fmt.Errorf("unsupported checkpoint schema %d",cp.SchemaVersion)};claimed:=cp.Checksum;cp.Checksum="";raw,_:=json.MarshalIndent(cp,"","  ");sum:=sha256.Sum256(raw);if claimed!=hex.EncodeToString(sum[:]){return errors.New("checkpoint checksum mismatch")};if cp.Generation==0{return errors.New("checkpoint generation is zero")};if len(cp.Desired.Routes)==0||len(cp.Desired.Pools)==0{return errors.New("checkpoint desired state incomplete")};return nil}
func (s *Store) pruneLocked(current uint64)error{entries,err:=os.ReadDir(s.dir);if err!=nil{return err};type item struct{g uint64;n string};var all []item;for _,e:=range entries{n:=e.Name();if !strings.HasPrefix(n,"generation-")||!strings.HasSuffix(n,".json"){continue};v:=strings.TrimSuffix(strings.TrimPrefix(n,"generation-"),".json");g,_:=strconv.ParseUint(v,10,64);all=append(all,item{g,n})};sort.Slice(all,func(i,j int)bool{return all[i].g>all[j].g});for i:=s.retain;i<len(all);i++{if all[i].g!=current{_ = os.Remove(filepath.Join(s.dir,all[i].n))}};return nil}
