package platform

import "strings"

func BuildIdentity(req Request) ArtifactIdentity {
	return ArtifactIdentity{
		Surface: normalizeSurface(req.Surface),
		Manager: normalizeManager(req.Manager),
		Name:    strings.TrimSpace(req.Name),
		Version: strings.TrimSpace(req.Version),
		Source:  normalizeSource(req.Source),
		Digest:  strings.TrimSpace(req.Digest),
	}
}

func InspectRequest(req Request) []PolicyViolation {
	identity := BuildIdentity(req)
	violations := make([]PolicyViolation, 0, 8)
	if strings.TrimSpace(req.RequestID) == "" {
		violations = append(violations, PolicyViolation{Code: "REQUEST_ID_MISSING", Message: "request id is required", Blocking: true})
	}
	if strings.TrimSpace(req.InstanceID) == "" {
		violations = append(violations, PolicyViolation{Code: "INSTANCE_ID_MISSING", Message: "instance identity is required", Blocking: true})
	}
	if identity.Surface == "" {
		violations = append(violations, PolicyViolation{Code: "SURFACE_MISSING", Message: "artifact surface is required", Blocking: true})
	}
	if identity.Manager == "" {
		violations = append(violations, PolicyViolation{Code: "MANAGER_MISSING", Message: "artifact manager is required", Blocking: true})
	}
	if identity.Name == "" {
		violations = append(violations, PolicyViolation{Code: "NAME_MISSING", Message: "artifact name is required", Blocking: true})
	}
	if identity.Source == "" {
		violations = append(violations, PolicyViolation{Code: "SOURCE_MISSING", Message: "artifact source is required", Blocking: true})
	}
	return violations
}

func NormalizeRequest(req Request) Request {
	req.Surface = normalizeSurface(req.Surface)
	req.Manager = normalizeManager(req.Manager)
	req.Name = strings.TrimSpace(req.Name)
	req.Version = strings.TrimSpace(req.Version)
	req.Source = normalizeSource(req.Source)
	req.Digest = strings.TrimSpace(req.Digest)
	req.Environment = strings.ToLower(strings.TrimSpace(req.Environment))
	req.Action = strings.ToLower(strings.TrimSpace(req.Action))
	return req
}

func ArtifactCoordinate(req Request) string {
	identity := BuildIdentity(req)
	return strings.Join([]string{identity.Surface, identity.Manager, identity.Name, identity.Version, identity.Digest}, ":")
}

func IsPackageManager(manager string) bool {
	switch normalizeManager(manager) {
	case "apt", "apt-get", "dpkg", "yum", "dnf", "rpm":
		return true
	default:
		return false
	}
}

func IsContainerManager(manager string) bool {
	switch normalizeManager(manager) {
	case "docker", "containerd", "nerdctl", "crictl":
		return true
	default:
		return false
	}
}

func IsDependencyManager(manager string) bool {
	switch normalizeManager(manager) {
	case "maven", "gradle", "npm", "pip", "go":
		return true
	default:
		return false
	}
}
