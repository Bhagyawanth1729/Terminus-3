package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"artifactguard/internal/core"
)

func readJSON(path string, dst interface{}) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, dst)
}

func required(fs *flag.FlagSet, name string) *string {
	return fs.String(name, "", name)
}

func need(values map[string]*string) error {
	for name, value := range values {
		if *value == "" {
			return fmt.Errorf("missing --%s", name)
		}
	}
	return nil
}

func parseNow(value string) (time.Time, error) {
	if value == "" {
		return time.Now().UTC(), nil
	}
	return time.Parse(time.RFC3339, value)
}

func evaluate(args []string) int {
	fs := flag.NewFlagSet("evaluate", flag.ContinueOnError)
	requestPath := required(fs, "request")
	policyPath := required(fs, "policy")
	scansPath := required(fs, "scans")
	exceptionsPath := required(fs, "exceptions")
	stateDir := required(fs, "state")
	secretPath := required(fs, "secret")
	nowValue := fs.String("now", "", "RFC3339 evaluation time")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if err := need(map[string]*string{"request": requestPath, "policy": policyPath, "scans": scansPath, "exceptions": exceptionsPath, "state": stateDir, "secret": secretPath}); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	var req core.Request
	var policy core.Policy
	var scans core.ScanDB
	var exceptions core.ExceptionDB
	if err := readJSON(*requestPath, &req); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := readJSON(*policyPath, &policy); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := readJSON(*scansPath, &scans); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := readJSON(*exceptionsPath, &exceptions); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	secret, err := os.ReadFile(*secretPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	now, err := parseNow(*nowValue)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	decision, err := core.Evaluate(policy, scans, exceptions, req, *stateDir, secret, now)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	_ = json.NewEncoder(os.Stdout).Encode(decision)
	if decision.Decision == "DENY" {
		return 42
	}
	return 0
}

func verifyPermit(args []string) int {
	fs := flag.NewFlagSet("verify-permit", flag.ContinueOnError)
	permitPath := required(fs, "permit")
	requestPath := required(fs, "request")
	policyPath := required(fs, "policy")
	secretPath := required(fs, "secret")
	stateDir := fs.String("state", os.Getenv("ARTIFACTGUARD_STATE_DIR"), "durable state directory for replay protection")
	nowValue := fs.String("now", "", "RFC3339 verification time")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if err := need(map[string]*string{"permit": permitPath, "request": requestPath, "policy": policyPath, "secret": secretPath}); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	var permit core.Permit
	var req core.Request
	var policy core.Policy
	if err := readJSON(*permitPath, &permit); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := readJSON(*requestPath, &req); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := readJSON(*policyPath, &policy); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	secret, err := os.ReadFile(*secretPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	now, err := parseNow(*nowValue)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	var valid bool
	var code string
	if *stateDir != "" {
		valid, code, err = core.VerifyPermitWithState(permit, req, policy, secret, *stateDir, now)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 2
		}
	} else {
		valid, code = core.VerifyPermit(permit, req, policy, secret, now)
	}
	_ = json.NewEncoder(os.Stdout).Encode(map[string]interface{}{"valid": valid, "code": code})
	if !valid {
		return 43
	}
	return 0
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: artifactguard <evaluate|verify-permit>")
		os.Exit(2)
	}
	var code int
	switch os.Args[1] {
	case "evaluate":
		code = evaluate(os.Args[2:])
	case "verify-permit":
		code = verifyPermit(os.Args[2:])
	default:
		fmt.Fprintln(os.Stderr, "unknown command")
		code = 2
	}
	os.Exit(code)
}
