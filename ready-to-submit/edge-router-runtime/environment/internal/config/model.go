package config

import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "net"
    "net/netip"
    "net/url"
    "os"
    "sort"
    "strconv"
    "strings"
    "time"
)

type Document struct {
    SchemaVersion int `json:"schema_version"`
    Generation uint64 `json:"generation"`
    Sources []SourceState `json:"sources"`
    Routes []Route `json:"routes"`
    Pools []Pool `json:"pools"`
    Defaults Defaults `json:"defaults"`
}

type SourceState struct {
    Name string `json:"name"`
    Revision uint64 `json:"revision"`
    Digest string `json:"digest,omitempty"`
}

type Defaults struct {
    ConnectTimeoutMS int `json:"connect_timeout_ms"`
    RequestTimeoutMS int `json:"request_timeout_ms"`
    DrainTimeoutMS int `json:"drain_timeout_ms"`
    HealthIntervalMS int `json:"health_interval_ms"`
    HealthTimeoutMS int `json:"health_timeout_ms"`
    AffinityTTLSeconds int `json:"affinity_ttl_seconds"`
    AffinityCapacity int `json:"affinity_capacity"`
}

type Route struct {
    ID string `json:"id"`
    Hosts []string `json:"hosts"`
    PathPrefix string `json:"path_prefix"`
    Methods []string `json:"methods"`
    Pool string `json:"pool"`
    FailoverPools []string `json:"failover_pools,omitempty"`
    Retry RetryPolicy `json:"retry"`
    Affinity AffinityPolicy `json:"affinity"`
    Headers []HeaderMatch `json:"headers,omitempty"`
    Priority int `json:"priority"`
}

type HeaderMatch struct {
    Name string `json:"name"`
    Exact string `json:"exact,omitempty"`
    Prefix string `json:"prefix,omitempty"`
}

type RetryPolicy struct {
    Attempts int `json:"attempts"`
    PerTryTimeoutMS int `json:"per_try_timeout_ms"`
    RetryOn []string `json:"retry_on"`
}

type AffinityPolicy struct {
    Mode string `json:"mode"`
    Header string `json:"header,omitempty"`
    Cookie string `json:"cookie,omitempty"`
    TTLSeconds int `json:"ttl_seconds,omitempty"`
    Capacity int `json:"capacity,omitempty"`
}

type Pool struct {
    ID string `json:"id"`
    Strategy string `json:"strategy"`
    Endpoints []Endpoint `json:"endpoints"`
    Health HealthPolicy `json:"health"`
    Transport TransportPolicy `json:"transport"`
    Affinity AffinityPolicy `json:"affinity"`
    Metadata map[string]string `json:"metadata,omitempty"`
}

type Endpoint struct {
    ID string `json:"id,omitempty"`
    Address string `json:"address"`
    Weight int `json:"weight"`
    Zone string `json:"zone,omitempty"`
    Metadata map[string]string `json:"metadata,omitempty"`
}

type HealthPolicy struct {
    Path string `json:"path"`
    IntervalMS int `json:"interval_ms"`
    TimeoutMS int `json:"timeout_ms"`
    HealthyThreshold int `json:"healthy_threshold"`
    UnhealthyThreshold int `json:"unhealthy_threshold"`
    ExpectedStatuses []int `json:"expected_statuses"`
}

type TransportPolicy struct {
    Scheme string `json:"scheme"`
    MaxIdleConns int `json:"max_idle_conns"`
    MaxIdleConnsPerHost int `json:"max_idle_conns_per_host"`
    IdleConnTimeoutMS int `json:"idle_conn_timeout_ms"`
    TLSInsecureSkipVerify bool `json:"tls_insecure_skip_verify"`
}

type Candidate struct {
    Source string
    Revision uint64
    Digest string
    Document Document
    ReceivedAt time.Time
}

type ValidationError struct {
    Path string `json:"path"`
    Message string `json:"message"`
}

func (e ValidationError) Error() string { return e.Path + ": " + e.Message }

func Load(path string) (Document, error) {
    raw, err := os.ReadFile(path)
    if err != nil { return Document{}, fmt.Errorf("read configuration: %w", err) }
    return Decode(raw)
}

func Decode(raw []byte) (Document, error) {
    var d Document
    dec := json.NewDecoder(strings.NewReader(string(raw)))
    dec.DisallowUnknownFields()
    if err := dec.Decode(&d); err != nil { return Document{}, fmt.Errorf("decode configuration: %w", err) }
    if err := Validate(d); err != nil { return Document{}, err }
    return d, nil
}

func Encode(d Document) ([]byte, error) {
    return json.MarshalIndent(d, "", "  ")
}

func Validate(d Document) error {
    var problems []error
    if d.SchemaVersion != 1 { problems = append(problems, ValidationError{"schema_version", "must be 1"}) }
    if len(d.Routes) == 0 { problems = append(problems, ValidationError{"routes", "at least one route is required"}) }
    if len(d.Pools) == 0 { problems = append(problems, ValidationError{"pools", "at least one pool is required"}) }
    poolIDs := map[string]struct{}{}
    for i, p := range d.Pools {
        path := fmt.Sprintf("pools[%d]", i)
        if !validID(p.ID) { problems = append(problems, ValidationError{path+".id", "invalid stable id"}) }
        if _, ok := poolIDs[p.ID]; ok { problems = append(problems, ValidationError{path+".id", "duplicate pool id"}) }
        poolIDs[p.ID] = struct{}{}
        if p.Strategy != "round_robin" && p.Strategy != "weighted" && p.Strategy != "least_inflight" { problems = append(problems, ValidationError{path+".strategy", "unsupported strategy"}) }
        if len(p.Endpoints) == 0 { problems = append(problems, ValidationError{path+".endpoints", "pool has no endpoints"}) }
        rawAddresses := map[string]struct{}{}
        for j, ep := range p.Endpoints {
            epPath := fmt.Sprintf("%s.endpoints[%d]", path, j)
            if ep.Weight <= 0 { problems = append(problems, ValidationError{epPath+".weight", "must be positive"}) }
            if _, err := NormalizeAddress(ep.Address, p.Transport.Scheme); err != nil { problems = append(problems, ValidationError{epPath+".address", err.Error()}) }
            key := strings.ToLower(strings.TrimSpace(ep.Address))
            if _, exists := rawAddresses[key]; exists { problems = append(problems, ValidationError{epPath+".address", "duplicate endpoint address"}) }
            rawAddresses[key] = struct{}{}
        }
        validateHealth(path+".health", p.Health, &problems)
        validateAffinity(path+".affinity", p.Affinity, &problems)
    }
    routeIDs := map[string]struct{}{}
    for i, r := range d.Routes {
        path := fmt.Sprintf("routes[%d]", i)
        if !validID(r.ID) { problems = append(problems, ValidationError{path+".id", "invalid stable id"}) }
        if _, ok := routeIDs[r.ID]; ok { problems = append(problems, ValidationError{path+".id", "duplicate route id"}) }
        routeIDs[r.ID] = struct{}{}
        if _, ok := poolIDs[r.Pool]; !ok { problems = append(problems, ValidationError{path+".pool", "unknown pool"}) }
        for _, f := range r.FailoverPools { if _, ok := poolIDs[f]; !ok { problems = append(problems, ValidationError{path+".failover_pools", "unknown pool "+f}) } }
        if r.PathPrefix == "" || !strings.HasPrefix(r.PathPrefix, "/") { problems = append(problems, ValidationError{path+".path_prefix", "must start with /"}) }
        if r.Retry.Attempts < 1 || r.Retry.Attempts > 8 { problems = append(problems, ValidationError{path+".retry.attempts", "must be between 1 and 8"}) }
        validateAffinity(path+".affinity", r.Affinity, &problems)
    }
    if len(problems) > 0 { return errors.Join(problems...) }
    return nil
}

func validateHealth(path string, h HealthPolicy, problems *[]error) {
    if h.Path == "" || !strings.HasPrefix(h.Path, "/") { *problems = append(*problems, ValidationError{path+".path", "must begin with /"}) }
    if h.IntervalMS < 50 { *problems = append(*problems, ValidationError{path+".interval_ms", "must be at least 50"}) }
    if h.TimeoutMS < 10 || h.TimeoutMS >= h.IntervalMS { *problems = append(*problems, ValidationError{path+".timeout_ms", "must be positive and less than interval"}) }
    if h.HealthyThreshold < 1 || h.UnhealthyThreshold < 1 { *problems = append(*problems, ValidationError{path, "thresholds must be positive"}) }
}

func validateAffinity(path string, a AffinityPolicy, problems *[]error) {
    switch a.Mode {
    case "", "none":
    case "header":
        if strings.TrimSpace(a.Header) == "" { *problems = append(*problems, ValidationError{path+".header", "required for header affinity"}) }
    case "cookie":
        if strings.TrimSpace(a.Cookie) == "" { *problems = append(*problems, ValidationError{path+".cookie", "required for cookie affinity"}) }
    default:
        *problems = append(*problems, ValidationError{path+".mode", "unsupported affinity mode"})
    }
}

func validID(v string) bool {
    if v == "" || len(v) > 96 { return false }
    for _, r := range v { if !(r == '-' || r == '_' || r == '.' || r >= '0' && r <= '9' || r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z') { return false } }
    return true
}

func Normalize(d Document) Document {
    out := d
    out.Pools = append([]Pool(nil), d.Pools...)
    out.Routes = append([]Route(nil), d.Routes...)
    for i := range out.Pools {
        p := &out.Pools[i]
        p.ID = strings.TrimSpace(p.ID)
        p.Strategy = strings.ToLower(strings.TrimSpace(p.Strategy))
        p.Endpoints = append([]Endpoint(nil), p.Endpoints...)
        for j := range p.Endpoints {
            p.Endpoints[j].Address = strings.TrimSpace(p.Endpoints[j].Address)
            p.Endpoints[j].Zone = strings.ToLower(strings.TrimSpace(p.Endpoints[j].Zone))
        }
    }
    for i := range out.Routes {
        r := &out.Routes[i]
        r.ID = strings.TrimSpace(r.ID)
        r.PathPrefix = cleanPath(r.PathPrefix)
        for j := range r.Hosts { r.Hosts[j] = strings.ToLower(strings.TrimSuffix(strings.TrimSpace(r.Hosts[j]), ".")) }
        for j := range r.Methods { r.Methods[j] = strings.ToUpper(strings.TrimSpace(r.Methods[j])) }
        sort.Strings(r.Hosts)
        sort.Strings(r.Methods)
        sort.Strings(r.FailoverPools)
    }
    return out
}

func cleanPath(p string) string {
    if p == "" { return "/" }
    parts := strings.Split(p, "/")
    out := make([]string, 0, len(parts))
    for _, part := range parts { if part != "" && part != "." { out = append(out, part) } }
    return "/" + strings.Join(out, "/")
}

func NormalizeAddress(raw, scheme string) (string, error) {
    raw = strings.TrimSpace(raw)
    if raw == "" { return "", errors.New("empty address") }
    if strings.Contains(raw, "://") {
        u, err := url.Parse(raw)
        if err != nil { return "", err }
        raw = u.Host
        if scheme == "" { scheme = u.Scheme }
    }
    host, port, err := net.SplitHostPort(raw)
    if err != nil {
        if strings.Count(raw, ":") == 0 {
            host = raw
            if scheme == "https" { port = "443" } else { port = "80" }
        } else { return "", fmt.Errorf("invalid host:port %q", raw) }
    }
    host = strings.Trim(host, "[]")
    if ip, err := netip.ParseAddr(host); err == nil { host = ip.String() } else { host = strings.ToLower(strings.TrimSuffix(host, ".")) }
    p, err := strconv.Atoi(port)
    if err != nil || p < 1 || p > 65535 { return "", fmt.Errorf("invalid port %q", port) }
    return net.JoinHostPort(host, strconv.Itoa(p)), nil
}

func DocumentDigest(d Document) string {
    b, _ := json.Marshal(d)
    sum := sha256.Sum256(b)
    return hex.EncodeToString(sum[:])
}

func PoolCompatibility(p Pool) string {
    parts := []string{p.ID, p.Transport.Scheme, strconv.Itoa(p.Transport.MaxIdleConnsPerHost)}
    for _, ep := range p.Endpoints { parts = append(parts, ep.Address, strconv.Itoa(ep.Weight), ep.Zone) }
    if p.Metadata != nil {
        keys := make([]string, 0, len(p.Metadata))
        for k := range p.Metadata { keys = append(keys, k) }
        sort.Strings(keys)
        for _, k := range keys { parts = append(parts, k+"="+p.Metadata[k]) }
    }
    sum := sha256.Sum256([]byte(strings.Join(parts, "|")))
    return hex.EncodeToString(sum[:8])
}

func RouteDigest(r Route) string {
    copy := r
    copy.Hosts = append([]string(nil), r.Hosts...)
    copy.Methods = append([]string(nil), r.Methods...)
    copy.FailoverPools = append([]string(nil), r.FailoverPools...)
    sort.Strings(copy.Hosts)
    sort.Strings(copy.Methods)
    sort.Strings(copy.FailoverPools)
    b, _ := json.Marshal(copy)
    sum := sha256.Sum256(b)
    return hex.EncodeToString(sum[:16])
}

func Merge(base Document, source Document) Document {
    out := base
    if len(source.Routes) > 0 { out.Routes = append([]Route(nil), source.Routes...) }
    if len(source.Pools) > 0 { out.Pools = append([]Pool(nil), source.Pools...) }
    if source.Defaults.ConnectTimeoutMS != 0 { out.Defaults = source.Defaults }
    byName := map[string]SourceState{}
    for _, s := range base.Sources { byName[s.Name] = s }
    for _, s := range source.Sources { byName[s.Name] = s }
    out.Sources = out.Sources[:0]
    for _, s := range byName { out.Sources = append(out.Sources, s) }
    sort.Slice(out.Sources, func(i,j int) bool { return out.Sources[i].Name < out.Sources[j].Name })
    return out
}
