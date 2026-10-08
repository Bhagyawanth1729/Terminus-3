package main

import(
    "flag"
    "fmt"
    "log"
    "os"

    "edge-router-runtime/internal/bootstrap"
)

func main(){if len(os.Args)<2{usage();os.Exit(2)};switch os.Args[1]{case "serve":serve(os.Args[2:]);case "validate":validate(os.Args[2:]);case "help","-h","--help":usage();default:fmt.Fprintf(os.Stderr,"unknown command %q\n",os.Args[1]);usage();os.Exit(2)}}
func serve(args []string){fs:=flag.NewFlagSet("serve",flag.ExitOnError);cfg:=fs.String("config","/app/config/production.json","configuration path");state:=fs.String("state-dir","/app/state","durable state directory");listen:=fs.String("listen",":8080","public listener");admin:=fs.String("admin-listen",":9901","operator listener");_ = fs.Parse(args);opts:=bootstrap.Options{ConfigPath:*cfg,StateDir:*state,Listen:*listen,AdminListen:*admin};bootstrap.LogOptions(opts);host:=bootstrap.New(opts);if err:=host.RunUntilSignal();err!=nil{log.Fatal(err)}}
func validate(args []string){fs:=flag.NewFlagSet("validate",flag.ExitOnError);cfg:=fs.String("config","/app/config/production.json","configuration path");_ = fs.Parse(args);if err:=bootstrap.ValidateOnly(*cfg);err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(1)};fmt.Println("configuration valid")}
func usage(){fmt.Fprintln(os.Stderr,"usage: edge-router-runtime <serve|validate> [flags]")}
