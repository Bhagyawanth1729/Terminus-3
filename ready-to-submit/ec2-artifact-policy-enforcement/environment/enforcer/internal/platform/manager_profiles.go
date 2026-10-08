package platform

import (
	"fmt"
	"regexp"
	"strings"
)

// ManagerProfile describes the operational differences between package,
// container and build dependency acquisition clients.  Profiles are consumed
// during every evaluation; they are not a catalog used only for counting.
type ManagerProfile struct {
	Name               string
	Surface            string
	Aliases            []string
	InstallActions     []string
	UpdateActions      []string
	RemoveActions      []string
	DefaultActionClass string
	SourceKind         string
	NameKind           string
	DigestKinds        []string
	RequireVersion     bool
	AllowEmptyAction   bool
	AllowSourcePath    bool
	AllowSourceScheme  bool
	CaseSensitiveName  bool
}

var (
	debianNameRE = regexp.MustCompile(`^[a-z0-9][a-z0-9+.-]*$`)
	rpmNameRE    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9+_.-]*$`)
	npmNameRE    = regexp.MustCompile(`^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$`)
	goModuleRE   = regexp.MustCompile(`^[A-Za-z0-9._~/-]+$`)
	mavenNameRE  = regexp.MustCompile(`^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$`)
	imageNameRE  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._/:@-]*$`)
)

func packageAPTProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "apt",
		Surface:            "package",
		Aliases:            []string{"apt", "apt-get"},
		InstallActions:     []string{"install", "download"},
		UpdateActions:      []string{"upgrade", "dist-upgrade", "reinstall"},
		RemoveActions:      []string{"remove", "purge"},
		DefaultActionClass: "install",
		SourceKind:         "debian-repository",
		NameKind:           "debian-package",
		DigestKinds:        []string{"sha256", "sha512"},
		RequireVersion:     false,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  false,
	}
}

func packageDPKGProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "dpkg",
		Surface:            "package",
		Aliases:            []string{"dpkg"},
		InstallActions:     []string{"install", "unpack"},
		UpdateActions:      []string{"configure", "reinstall"},
		RemoveActions:      []string{"remove", "purge"},
		DefaultActionClass: "install",
		SourceKind:         "debian-artifact-source",
		NameKind:           "debian-package",
		DigestKinds:        []string{"sha256", "sha512"},
		RequireVersion:     false,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  false,
	}
}

func packageYUMProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "yum",
		Surface:            "package",
		Aliases:            []string{"yum"},
		InstallActions:     []string{"install", "localinstall"},
		UpdateActions:      []string{"update", "upgrade", "reinstall", "downgrade"},
		RemoveActions:      []string{"remove", "erase"},
		DefaultActionClass: "install",
		SourceKind:         "rpm-repository",
		NameKind:           "rpm-package",
		DigestKinds:        []string{"sha256", "sha512"},
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
	}
}

func packageDNFProfile() ManagerProfile {
	profile := packageYUMProfile()
	profile.Name = "dnf"
	profile.Aliases = []string{"dnf", "dnf5"}
	profile.InstallActions = []string{"install", "download"}
	profile.UpdateActions = []string{"upgrade", "reinstall", "downgrade", "distro-sync"}
	profile.SourceKind = "dnf-repository"
	return profile
}

func packageRPMProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "rpm",
		Surface:            "package",
		Aliases:            []string{"rpm"},
		InstallActions:     []string{"install", "upgrade", "freshen"},
		UpdateActions:      []string{"reinstall", "replace"},
		RemoveActions:      []string{"erase"},
		DefaultActionClass: "install",
		SourceKind:         "rpm-artifact-source",
		NameKind:           "rpm-package",
		DigestKinds:        []string{"sha256", "sha512"},
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
	}
}

func containerDockerProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "docker",
		Surface:            "container",
		Aliases:            []string{"docker"},
		InstallActions:     []string{"pull", "create", "run"},
		UpdateActions:      []string{"build", "load", "import"},
		RemoveActions:      []string{"remove", "rmi"},
		DefaultActionClass: "install",
		SourceKind:         "oci-registry",
		NameKind:           "oci-reference",
		DigestKinds:        []string{"sha256", "sha512"},
		RequireVersion:     false,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  false,
	}
}

func containerContainerdProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "containerd",
		Surface:            "container",
		Aliases:            []string{"containerd", "ctr"},
		InstallActions:     []string{"pull", "fetch", "import"},
		UpdateActions:      []string{"unpack", "mount"},
		RemoveActions:      []string{"remove", "rm"},
		DefaultActionClass: "install",
		SourceKind:         "oci-registry",
		NameKind:           "oci-reference",
		DigestKinds:        []string{"sha256", "sha512"},
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
	}
}

func containerNerdctlProfile() ManagerProfile {
	profile := containerDockerProfile()
	profile.Name = "nerdctl"
	profile.Aliases = []string{"nerdctl"}
	profile.UpdateActions = []string{"build", "load"}
	return profile
}

func containerCRIProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "crictl",
		Surface:            "container",
		Aliases:            []string{"crictl", "cri-o", "crio"},
		InstallActions:     []string{"pull", "create", "run"},
		UpdateActions:      []string{"inspect", "reopen"},
		RemoveActions:      []string{"remove", "rmi"},
		DefaultActionClass: "install",
		SourceKind:         "cri-registry",
		NameKind:           "oci-reference",
		DigestKinds:        []string{"sha256", "sha512"},
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
	}
}

func dependencyMavenProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "maven",
		Surface:            "dependency",
		Aliases:            []string{"maven", "mvn"},
		InstallActions:     []string{"resolve", "download", "install"},
		UpdateActions:      []string{"update", "verify", "package"},
		RemoveActions:      []string{"purge"},
		DefaultActionClass: "install",
		SourceKind:         "maven-repository",
		NameKind:           "maven-coordinate",
		DigestKinds:        []string{"sha256", "sha512"},
		RequireVersion:     true,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  true,
	}
}

func dependencyGradleProfile() ManagerProfile {
	profile := dependencyMavenProfile()
	profile.Name = "gradle"
	profile.Aliases = []string{"gradle", "gradlew"}
	profile.InstallActions = []string{"resolve", "dependencies", "build"}
	profile.UpdateActions = []string{"refresh", "verify", "assemble"}
	profile.SourceKind = "gradle-repository"
	return profile
}

func dependencyNPMProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "npm",
		Surface:            "dependency",
		Aliases:            []string{"npm", "npm-ci", "yarn", "pnpm"},
		InstallActions:     []string{"install", "ci", "add", "fetch"},
		UpdateActions:      []string{"update", "audit-fix"},
		RemoveActions:      []string{"remove", "uninstall"},
		DefaultActionClass: "install",
		SourceKind:         "npm-registry",
		NameKind:           "npm-package",
		DigestKinds:        []string{"sha256", "sha512"},
		RequireVersion:     false,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  false,
	}
}

func dependencyPIPProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "pip",
		Surface:            "dependency",
		Aliases:            []string{"pip", "pip3", "python-pip"},
		InstallActions:     []string{"install", "download", "wheel"},
		UpdateActions:      []string{"upgrade", "sync"},
		RemoveActions:      []string{"uninstall"},
		DefaultActionClass: "install",
		SourceKind:         "python-index",
		NameKind:           "python-distribution",
		DigestKinds:        []string{"sha256", "sha512"},
		RequireVersion:     false,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  false,
	}
}

func dependencyGoProfile() ManagerProfile {
	return ManagerProfile{
		Name:               "go",
		Surface:            "dependency",
		Aliases:            []string{"go", "gomod", "goproxy"},
		InstallActions:     []string{"get", "download", "install"},
		UpdateActions:      []string{"tidy", "mod", "upgrade"},
		RemoveActions:      []string{"drop"},
		DefaultActionClass: "install",
		SourceKind:         "go-proxy",
		NameKind:           "go-module",
		DigestKinds:        []string{"sha256", "h1"},
		RequireVersion:     true,
		AllowEmptyAction:   true,
		AllowSourcePath:    true,
		AllowSourceScheme:  true,
		CaseSensitiveName:  true,
	}
}

func managerProfiles() []ManagerProfile {
	return []ManagerProfile{
		packageAPTProfile(),
		packageDPKGProfile(),
		packageYUMProfile(),
		packageDNFProfile(),
		packageRPMProfile(),
		containerDockerProfile(),
		containerContainerdProfile(),
		containerNerdctlProfile(),
		containerCRIProfile(),
		dependencyMavenProfile(),
		dependencyGradleProfile(),
		dependencyNPMProfile(),
		dependencyPIPProfile(),
		dependencyGoProfile(),
	}
}

func UnknownManagerProfile(surface, manager string) ManagerProfile {
	return ManagerProfile{
		Name:               strings.ToLower(strings.TrimSpace(manager)),
		Surface:            strings.ToLower(strings.TrimSpace(surface)),
		DefaultActionClass: "other",
		SourceKind:         "unknown",
		NameKind:           "unknown",
	}
}

func ResolveManagerProfile(surface, manager string) (ManagerProfile, bool) {
	surface = strings.ToLower(strings.TrimSpace(surface))
	manager = strings.ToLower(strings.TrimSpace(manager))
	for _, profile := range managerProfiles() {
		if profile.Surface != surface {
			continue
		}
		if profile.Name == manager || contains(profile.Aliases, manager) {
			return profile, true
		}
	}
	return UnknownManagerProfile(surface, manager), false
}

func profileAllowsAction(profile ManagerProfile, action string) bool {
	action = strings.ToLower(strings.TrimSpace(action))
	if action == "" {
		return profile.AllowEmptyAction
	}
	// The external request contract uses "install" as the generic admission
	// operation for all three surfaces; manager-specific verbs are accepted in
	// addition to that stable compatibility action.
	if action == "install" && profile.DefaultActionClass == "install" {
		return true
	}
	return contains(profile.InstallActions, action) || contains(profile.UpdateActions, action) || contains(profile.RemoveActions, action)
}

func validateDebianPackageName(name string) bool {
	return debianNameRE.MatchString(strings.ToLower(name))
}

func validateRPMPackageName(name string) bool {
	return rpmNameRE.MatchString(name)
}

func validateOCIName(name string) bool {
	if !imageNameRE.MatchString(name) {
		return false
	}
	return !strings.Contains(name, "..") && !strings.HasPrefix(name, "/") && !strings.HasSuffix(name, "/")
}

func validateDependencyName(kind, name string) bool {
	switch kind {
	case "maven-coordinate":
		if strings.Contains(name, ":") {
			return mavenNameRE.MatchString(name)
		}
		return rpmNameRE.MatchString(name)
	case "npm-package":
		return npmNameRE.MatchString(strings.ToLower(name))
	case "python-distribution":
		return debianNameRE.MatchString(strings.ToLower(strings.ReplaceAll(name, "_", "-")))
	case "go-module":
		return goModuleRE.MatchString(name)
	default:
		return strings.TrimSpace(name) != ""
	}
}

func (profile ManagerProfile) ValidateRequest(req Request) []PolicyViolation {
	violations := make([]PolicyViolation, 0, 8)
	if profile.Name == "" || profile.Surface == "" {
		return violations
	}
	if normalizeSurface(req.Surface) != profile.Surface {
		violations = append(violations, PolicyViolation{
			Code:     "SURFACE_MANAGER_MISMATCH",
			Message:  fmt.Sprintf("manager %s is not valid for %s acquisition", profile.Name, req.Surface),
			Blocking: true,
		})
	}
	if !profileAllowsAction(profile, req.Action) {
		violations = append(violations, PolicyViolation{
			Code:     "ACTION_UNSUPPORTED",
			Message:  fmt.Sprintf("action %q is unsupported by %s", req.Action, profile.Name),
			Blocking: true,
		})
	}
	name := strings.TrimSpace(req.Name)
	switch profile.NameKind {
	case "debian-package":
		if !validateDebianPackageName(name) {
			violations = append(violations, PolicyViolation{Code: "PACKAGE_NAME_INVALID", Message: "invalid Debian package name", Blocking: true})
		}
	case "rpm-package":
		if !validateRPMPackageName(name) {
			violations = append(violations, PolicyViolation{Code: "PACKAGE_NAME_INVALID", Message: "invalid RPM package name", Blocking: true})
		}
	case "oci-reference":
		if !validateOCIName(name) {
			violations = append(violations, PolicyViolation{Code: "IMAGE_REFERENCE_INVALID", Message: "invalid OCI artifact reference", Blocking: true})
		}
	default:
		if !validateDependencyName(profile.NameKind, name) {
			violations = append(violations, PolicyViolation{Code: "DEPENDENCY_NAME_INVALID", Message: "invalid dependency coordinate", Blocking: true})
		}
	}
	if profile.RequireVersion && strings.TrimSpace(req.Version) == "" {
		violations = append(violations, PolicyViolation{Code: "VERSION_MISSING", Message: "manager requires a versioned artifact coordinate", Blocking: true})
	}
	if source := strings.TrimSpace(req.Source); source == "" {
		violations = append(violations, PolicyViolation{Code: "SOURCE_MISSING", Message: "artifact source is required", Blocking: true})
	} else {
		if !profile.AllowSourceScheme && strings.Contains(source, "://") {
			violations = append(violations, PolicyViolation{Code: "SOURCE_SCHEME_INVALID", Message: "source URI scheme is unsupported by manager", Blocking: true})
		}
		if !profile.AllowSourcePath && strings.Contains(strings.TrimPrefix(source, "https://"), "/") {
			violations = append(violations, PolicyViolation{Code: "SOURCE_PATH_INVALID", Message: "source path is unsupported by manager", Blocking: true})
		}
	}
	return violations
}

func ManagerFamily(profile ManagerProfile) string {
	switch profile.Surface {
	case "package":
		if profile.Name == "apt" || profile.Name == "dpkg" {
			return "debian"
		}
		return "rpm"
	case "container":
		return "oci"
	case "dependency":
		switch profile.Name {
		case "maven", "gradle":
			return "jvm"
		case "npm":
			return "node"
		case "pip":
			return "python"
		case "go":
			return "golang"
		}
	}
	return "unknown"
}

func ManagerDigestKinds(profile ManagerProfile) []string {
	out := make([]string, len(profile.DigestKinds))
	copy(out, profile.DigestKinds)
	return out
}

func ManagerSupportsMutation(profile ManagerProfile) bool {
	return len(profile.UpdateActions) > 0
}

func ManagerSupportsRemoval(profile ManagerProfile) bool {
	return len(profile.RemoveActions) > 0
}

func ManagerOperationSummary(profile ManagerProfile) map[string]interface{} {
	return map[string]interface{}{
		"manager":         profile.Name,
		"surface":         profile.Surface,
		"family":          ManagerFamily(profile),
		"source_kind":     profile.SourceKind,
		"name_kind":       profile.NameKind,
		"digest_kinds":    ManagerDigestKinds(profile),
		"install_actions": append([]string(nil), profile.InstallActions...),
		"update_actions":  append([]string(nil), profile.UpdateActions...),
		"remove_actions":  append([]string(nil), profile.RemoveActions...),
	}
}
