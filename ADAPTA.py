# -*- coding: utf-8 -*-
"""AURION DYNAMIC - painel local integrado.
Chat/Agente (Ollama), ComfyUI, modelos, geracao por workflow,
render/CUDA/NVIDIA, Git, dependencias, CMD e logs.
"""
from __future__ import annotations
import json, os, re, shutil, socket, subprocess, sys, threading, time, urllib.error, urllib.request, webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
try:
    from flask import Flask, jsonify, request, render_template_string
except ImportError:
    subprocess.check_call([sys.executable,"-m","pip","install","flask"])
    from flask import Flask, jsonify, request, render_template_string

PROJECT=Path(r"C:\Users\ADM_PESS\Desktop\painelseguro#1 - Copia")
MODELS=PROJECT/"models"; DOWNLOADS=PROJECT/"_downloads"; LOG_DIR=PROJECT/"_aurion_logs"; WORKFLOWS=PROJECT/"workflows"; SCAN_DIR=PROJECT/"scan"; SCAN_REPORT=SCAN_DIR/"catalogo.json"; SCAN_JSONL=SCAN_DIR/"arquivos.jsonl"; CHAT_FILE=PROJECT/"chat_history.json"
MEMORY_DIR=PROJECT/"memoria"; MENTE_DIR=PROJECT/"mente"; FRAG_DIR=PROJECT/"fragmentos"; CLIENT_DIR=PROJECT/"clientes"; PROJECTS_DIR=PROJECT/"projetos"
HOST="127.0.0.1"; PORT=5000; COMFY_PORT=8188; OLLAMA_PORT=11434; OPENWEBUI_PORT=8080
COMFY_URL=f"http://127.0.0.1:{COMFY_PORT}"; OLLAMA_URL=f"http://127.0.0.1:{OLLAMA_PORT}"; OPENWEBUI_URL=f"http://127.0.0.1:{OPENWEBUI_PORT}"
COMFY_PORTABLE_URL="https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z"
SEVENZIP_URL="https://www.7-zip.org/a/7zr.exe"
OLLAMA_PREFERRED=["qwen3.5:4b","qwen3:8b","llama3.2:3b","llava:7b","deepseek-r1:7b"]
IGNORE={"Windows","Program Files","Program Files (x86)","Arquivos de Programas","PerfLogs","System","System32","AppData","Microsoft","Microsoft.NET","WindowsApps","$Recycle.Bin","System Volume Information","Recovery","ProgramData","node_modules",".git"}
MODEL_EXT={".safetensors",".ckpt",".pt",".pth",".bin",".gguf",".onnx",".sft"}
MODEL_CATEGORIES=("checkpoints","diffusion_models","vae","text_encoders","loras","controlnet","clip","clip_vision","unet","upscale_models","embeddings","ipadapter","photomaker","style_models","gligen","hypernetworks","vae_approx")
MODEL_ROOT_HINTS=(Path(r"F:\models"),Path(r"C:\models"),Path(r"D:\models"))
BRAIN_FILE=PROJECT/"aurion_brain.json"
CONFIG_FILE=PROJECT/"aurion_config.json"
CONFIG={"operator":"","comfy_url":COMFY_URL,"ollama_url":OLLAMA_URL,"reference_notes":"","huggingface_repos":[]}
AUTOMATION_INTERVAL=20
MAINTENANCE_INTERVAL=900
app=Flask(__name__)
STATE:dict[str,Any]={"busy":False,"operation":"","progress":0,"message":"AURION pronto.","logs":[],"errors":[],"scan":None,"agent_model":None,"startup_done":False,"startup":{},"image_job":None,"automation":{"enabled":True,"last_check":None,"last_maintenance":None,"actions":[]},"brain":{"generations":[],"operator_notes":"","learned":{}}}
_CACHE={"inventory":None,"inventory_at":0.0,"comfy":None,"comfy_at":0.0,"model_roots":None,"model_roots_at":0.0}
LOCK=threading.Lock()

def load_brain():
    try:
        if BRAIN_FILE.exists():
            d=json.loads(BRAIN_FILE.read_text(encoding="utf-8"))
            if isinstance(d,dict):
                with LOCK: STATE["brain"].update(d)
    except Exception: pass
def save_brain():
    try:
        with LOCK:d=json.loads(json.dumps(STATE["brain"],ensure_ascii=False))
        BRAIN_FILE.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:pass
def brain_event(kind,data):
    with LOCK:
        b=STATE["brain"]
        if kind=="generation":
            b.setdefault("generations",[]).append(data);b["generations"]=b["generations"][-50:]
        elif kind=="learned":b.setdefault("learned",{}).update(data)
    save_brain()
def load_config():
    global CONFIG
    try:
        if CONFIG_FILE.exists():
            d=json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(d,dict):CONFIG.update(d)
    except Exception:pass
def save_config(data):
    global CONFIG
    CONFIG.update({k:v for k,v in data.items() if k in {"operator","comfy_url","ollama_url","reference_notes","huggingface_repos","agent_model"}})
    global COMFY_URL, OLLAMA_URL
    if isinstance(CONFIG.get("comfy_url"),str) and CONFIG["comfy_url"].startswith("http"):COMFY_URL=CONFIG["comfy_url"].rstrip("/")
    if isinstance(CONFIG.get("ollama_url"),str) and CONFIG["ollama_url"].startswith("http"):OLLAMA_URL=CONFIG["ollama_url"].rstrip("/")
    CONFIG_FILE.write_text(json.dumps(CONFIG,ensure_ascii=False,indent=2),encoding="utf-8")
    if CONFIG.get("agent_model"):
        with LOCK:STATE["agent_model"]=CONFIG["agent_model"]
def ensure_dirs():
    for p in (PROJECT,MODELS,DOWNLOADS,LOG_DIR,WORKFLOWS,SCAN_DIR,MEMORY_DIR,MENTE_DIR,FRAG_DIR,CLIENT_DIR,PROJECTS_DIR):p.mkdir(parents=True,exist_ok=True)
    load_brain();load_config()
def log(msg,error=False):
    line=f"[{datetime.now():%H:%M:%S}] {msg}"
    with LOCK:
        STATE["logs"]=(STATE["logs"]+[line])[-300:]; STATE["message"]=msg
        if error: STATE["errors"]=(STATE["errors"]+[line])[-150:]
    try:
        (LOG_DIR/"aurion.log").open("a",encoding="utf-8").write(line+"\n")
        if error: (LOG_DIR/"errors.log").open("a",encoding="utf-8").write(line+"\n")
    except Exception: pass
def progress(v,msg=None):
    with LOCK: STATE["progress"]=max(0,min(100,int(v))); STATE["message"]=msg or STATE["message"]
    if msg: log(msg)
def bg(name,fn,*a,**kw):
    with LOCK:
        if STATE["busy"]: return False
        STATE.update(busy=True,operation=name,progress=0)
    def worker():
        try: fn(*a,**kw)
        except Exception as e: log(f"ERRO em {name}: {type(e).__name__}: {e}",True)
        finally:
            with LOCK:
                STATE["busy"]=False; STATE["operation"]=""
                if STATE.get("progress",0)<100 and "erro" in str(STATE.get("message","")).lower(): STATE["progress"]=100
    threading.Thread(target=worker,daemon=True).start(); return True
def exists(cmd): return shutil.which(cmd) is not None
def version(cmd):
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=8,encoding="utf-8",errors="ignore"); return (p.stdout or p.stderr or "").strip().splitlines()[0]
    except Exception:return ""
def port(port):
    s=socket.socket(); s.settimeout(.6)
    try:return s.connect_ex(("127.0.0.1",port))==0
    finally:s.close()
def http_json(url,timeout=5):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"AURION/2.0"}),timeout=timeout) as r:return json.loads(r.read().decode("utf-8",errors="ignore"))
    except Exception:return None
def post_json(url,payload,timeout=30):
    req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json","User-Agent":"AURION/2.1"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            raw=r.read().decode("utf-8",errors="ignore")
            try:return json.loads(raw)
            except Exception:return {"raw":raw}
    except urllib.error.HTTPError as e:
        raw=e.read().decode("utf-8",errors="ignore") if e.fp else ""
        detail=raw.strip() or str(e.reason)
        raise RuntimeError(f"HTTP {e.code} em {url}: {detail[:5000]}") from e
def hsize(n):
    x=float(max(0,n))
    for u in ("B","KB","MB","GB","TB"):
        if x<1024:return f"{x:.1f} {u}"
        x/=1024
    return f"{x:.1f} PB"
def rel(p,b):
    try:return str(p.resolve().relative_to(b.resolve()))
    except Exception:return str(p)
def exe(name,extra=None):
    x=shutil.which(name)
    if x:return x
    for p in extra or []:
        if p.exists():return str(p)
    return None

# ---------------- ComfyUI ----------------
def comfy_candidates(max_depth=5):
    roots=[PROJECT,PROJECT.parent,Path.home()/"Desktop",Path.home()/"Downloads",Path.home()/"Documents"]
    for l in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        p=Path(f"{l}:\\")
        if p.exists():roots.append(p)
    out=[]; seen=set()
    def add(d):
        try:d=d.resolve()
        except Exception:pass
        main=d/"main.py"
        if not main.exists() or d.name.lower()!="comfyui":return
        if not any((d/x).exists() for x in ("nodes.py","folder_paths.py","custom_nodes")):return
        k=str(d).lower()
        if k in seen:return
        seen.add(k); py=None
        for x in (d.parent/"python_embeded"/"python.exe",d/"python_embeded"/"python.exe"):
            if x.exists():py=x;break
        if py is None:py=Path(sys.executable)
        out.append({"path":str(d),"main":str(main),"python":str(py),"portable":"python_embeded" in str(py).lower()})
    for root in roots:
        if not root.exists():continue
        try:
            for cur,dirs,files in os.walk(root):
                p=Path(cur)
                try:depth=len(p.relative_to(root).parts)
                except Exception:depth=max_depth+1
                if depth>max_depth:dirs[:]=[];continue
                dirs[:]=[d for d in dirs if d not in IGNORE and not d.startswith('.')]
                if p.name.lower()=="comfyui" and "main.py" in files:add(p)
        except (PermissionError,OSError):pass
    out.sort(key=lambda x:(not x["portable"],PROJECT.as_posix().lower() not in x["path"].lower(),len(x["path"])))
    return out
def comfy():
    now=time.time()
    if _CACHE.get("comfy") is not None and now-_CACHE.get("comfy_at",0)<30:
        d=dict(_CACHE["comfy"]);d["running"]=port(COMFY_PORT);return d
    cs=comfy_candidates();c=cs[0] if cs else None
    d={"found":False,"path":None,"main":None,"python":None,"portable":False,"running":port(COMFY_PORT),"candidates":cs} if not c else {**c,"found":True,"running":port(COMFY_PORT),"candidates":cs}
    _CACHE["comfy"]=d;_CACHE["comfy_at"]=now
    return d

def configure_comfy():
    c=comfy()
    if not c["found"]:raise RuntimeError("ComfyUI não encontrado.")
    p=Path(c["path"])/"extra_model_paths.yaml";roots=configured_model_roots()
    if MODELS not in roots:roots.insert(0,MODELS)
    blocks=["# AURION DYNAMIC - modelos externos",""]
    for i,r in enumerate(roots):
        blocks += [f"{'aurion' if i==0 else f'aurion_{i}'}:",f"  base_path: {r.as_posix()}"]
        for cat in MODEL_CATEGORIES:blocks.append(f"  {cat}: {cat}/")
        blocks.append("")
    if p.exists():
        try:shutil.copy2(p,p.with_name(f"extra_model_paths.yaml.aurion_{datetime.now():%Y%m%d_%H%M%S}.bak"))
        except Exception:pass
    p.write_text("\n".join(blocks)+"\n",encoding="utf-8");_CACHE["inventory"]=None;_CACHE["model_roots"]=None
    log("Modelos externos ligados ao ComfyUI: "+", ".join(map(str,roots)));return True

def comfy_stats():return http_json(f"{COMFY_URL}/system_stats",5) if port(COMFY_PORT) else None

def start_comfy():
    c=comfy()
    if not c["found"]:log("ComfyUI não encontrado.",True);return False
    if c["running"]:log("ComfyUI já está ONLINE.");return True
    configure_comfy(); cmd=[c["python"],c["main"],"--listen","127.0.0.1","--port",str(COMFY_PORT)]
    log("Iniciando ComfyUI...")
    subprocess.Popen(cmd,cwd=c["path"],creationflags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(40):
        if port(COMFY_PORT):log(f"ComfyUI ONLINE: {COMFY_URL}");return True
        time.sleep(1)
    log("ComfyUI não respondeu.",True);return False

# ---------------- Models / Ollama ----------------
def classify_model_path(path):
    s=str(path).lower().replace("\\","/");n=Path(path).name.lower()
    if "/loras/" in s or "/lora/" in s or "lora" in n:return "loras"
    if "/controlnet/" in s or "/controlnets/" in s or "controlnet" in n:return "controlnet"
    if "/vae/" in s or n.startswith("vae") or "_vae" in n:return "vae"
    if "/text_encoders/" in s or "/clip/" in s or "text_encoder" in n:return "text_encoders"
    if "/diffusion_models/" in s or "/unet/" in s or "diffusion" in n:return "diffusion_models"
    if "/upscale_models/" in s or "/upscale/" in s or "upscale" in n:return "upscale_models"
    if "/embeddings/" in s or "/embedding/" in s:return "embeddings"
    if "/clip_vision/" in s:return "clip_vision"
    return "checkpoints"
def guess_architecture(name):
    n=str(name).lower()
    if any(x in n for x in ("flux","schnell","dev")):return "FLUX"
    if any(x in n for x in ("sd3","stable-diffusion-3")):return "SD3"
    if any(x in n for x in ("sdxl","juggernautxl","realvisxl","pony","xl")):return "SDXL"
    if any(x in n for x in ("sd1.5","sd15","1.5","dreamshaper","realisticvision")):return "SD1.5"
    if any(x in n for x in ("sd2","2.0","2.1")):return "SD2.x"
    return "checkpoint"
def discover_model_roots():
    """Descobre pastas de modelos reais sem entrar em áreas protegidas do Windows."""
    now=time.time()
    if _CACHE.get("model_roots") is not None and now-_CACHE.get("model_roots_at",0)<600:
        return _CACHE["model_roots"]
    roots=[];seen=set()
    def add(p):
        try:p=Path(p).resolve()
        except Exception:return
        if not p.exists() or not p.is_dir():return
        k=str(p).lower()
        if k not in seen:seen.add(k);roots.append(p)
    add(MODELS)
    for p in MODEL_ROOT_HINTS:add(p)
    c=comfy()
    if c.get("found"):
        cp=Path(c["path"]);add(cp/"models")
        y=cp/"extra_model_paths.yaml"
        if y.exists():
            try:
                import yaml
                data=yaml.safe_load(y.read_text(encoding="utf-8",errors="ignore")) or {}
                if isinstance(data,dict):
                    for block in data.values():
                        if isinstance(block,dict) and block.get("base_path"):
                            base=Path(str(block["base_path"]))
                            if not base.is_absolute():base=cp/base
                            add(base)
                            for cat in MODEL_CATEGORIES:
                                raw=block.get(cat)
                                if isinstance(raw,str):add(base/Path(raw))
            except Exception:pass
    names={"models","modelos"}|set(x.lower() for x in MODEL_CATEGORIES)
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive=Path(f"{letter}:\\")
        try:
            if not drive.exists():continue
            for cur,dirs,files in os.walk(drive,topdown=True):
                curp=Path(cur)
                try:depth=len(curp.relative_to(drive).parts)
                except Exception:depth=99
                dirs[:]=[d for d in dirs if d not in IGNORE and not d.startswith(".")]
                if depth>5:dirs[:]=[];continue
                if curp.name.lower() in names:
                    add(curp)
                    for d in list(dirs):
                        if d.lower() in names:add(curp/d)
        except (OSError,PermissionError):pass
    _CACHE["model_roots"]=roots;_CACHE["model_roots_at"]=now
    return roots

def configured_model_roots():return discover_model_roots()

def inventory(force=False):
    now=time.time()
    if not force and _CACHE.get("inventory") is not None and now-_CACHE.get("inventory_at",0)<20:
        return _CACHE["inventory"]
    files=[];counts={};categories={};total=0;seen=set();roots=configured_model_roots()
    for root in roots:
        try:
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in MODEL_EXT or any(part in IGNORE for part in p.parts):continue
                try:k=str(p.resolve()).lower()
                except Exception:k=str(p).lower()
                if k in seen:continue
                seen.add(k)
                try:n=p.stat().st_size
                except OSError:n=0
                ext=p.suffix.lower();cat=classify_model_path(p);total+=n
                counts[ext]=counts.get(ext,0)+1;categories[cat]=categories.get(cat,0)+1
                if len(files)<10000:
                    files.append({"name":p.name,"path":str(p),"relative":rel(p,root),"root":str(root),
                                  "size":hsize(n),"bytes":n,"ext":ext,"category":cat,"architecture":guess_architecture(p.name)})
        except (OSError,PermissionError):pass
    files.sort(key=lambda x:(x["category"],x["name"].lower(),x["path"].lower()))
    result={"counts":counts,"categories":categories,"total":len(files),"bytes":total,"size":hsize(total),"files":files,"roots":[str(x) for x in roots]}
    _CACHE["inventory"]=result;_CACHE["inventory_at"]=now
    return result

def model_folders():
    inv=inventory();out={k:0 for k in MODEL_CATEGORIES}
    for f in inv["files"]:out[f["category"]]=out.get(f["category"],0)+1
    return out

def ollama_models():
    d=http_json(f"{OLLAMA_URL}/api/tags",5);return d.get("models",[]) if isinstance(d,dict) else []
def choose_model():
    ms=ollama_models();names=[m.get("name") for m in ms if m.get("name")]
    if not names:return None
    with LOCK:cur=STATE.get("agent_model") or CONFIG.get("agent_model")
    if cur in names:chosen=cur
    else:
        pref={n:i for i,n in enumerate(OLLAMA_PREFERRED)};chosen=min(names,key=lambda n:pref.get(n,999))
    with LOCK:STATE["agent_model"]=chosen
    return chosen

def start_ollama():
    if port(OLLAMA_PORT):choose_model();log(f"Ollama ONLINE — agente carregado: {STATE.get('agent_model')}");return True
    x=exe("ollama",[Path(os.environ.get("LOCALAPPDATA",""))/"Programs/Ollama/ollama.exe",Path(r"C:\Program Files\Ollama\ollama.exe")])
    if not x:log("Ollama não encontrado.",True);return False
    log("Iniciando Ollama...");subprocess.Popen([x,"serve"],creationflags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(25):
        if port(OLLAMA_PORT):choose_model();log(f"Agente carregado: {STATE.get('agent_model')}");return True
        time.sleep(1)
    log("Ollama não respondeu.",True);return False
def start_webui():
    if port(OPENWEBUI_PORT):log("Open WebUI já está ONLINE.");return True
    candidates=[];x=exe("open-webui")
    if x:candidates.append([x,"serve"])
    candidates.append([sys.executable,"-m","open_webui","serve"])
    scripts=Path(sys.executable).parent
    for name in ("open-webui.exe","open-webui.cmd","open-webui"):
        p=scripts/name
        if p.exists():candidates.insert(0,[str(p),"serve"])
    last=None;log("Iniciando Open WebUI...")
    for cmd in candidates:
        try:
            subprocess.Popen(cmd,cwd=str(PROJECT),creationflags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0),
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(35):
                if port(OPENWEBUI_PORT):log(f"Open WebUI ONLINE: {OPENWEBUI_URL}");return True
                time.sleep(1)
        except Exception as e:last=e
    log(f"Open WebUI não respondeu: {last or 'comando não encontrado'}",True);return False

def load_scan_summary_for_agent(message=""):
    """Entrega ao agente apenas fatos encontrados pelo AURION."""
    data={}
    try:
        if SCAN_REPORT.exists(): data=json.loads(SCAN_REPORT.read_text(encoding="utf-8"))
    except Exception: data={}
    if not data: return {"status":"SEM_SCAN_SALVO"}
    low=message.lower()
    ctx={"timestamp":data.get("timestamp"),"label":data.get("label"),"arquivos":data.get("arquivos",0),"pastas":data.get("pastas",0),"tamanho":data.get("tamanho","0 B"),"por_tipo":data.get("por_tipo",{}),"clientes":data.get("clientes",{}),"projetos":data.get("projetos",{}),"repositorios":data.get("repositorios",[])[:100]}
    if any(k in low for k in ("arquivo","arquivos","projeto","projetos","cliente","clientes","scan","pasta","pastas")):
        q=message.strip()
        terms=[x for x in q.replace("?"," ").replace(","," ").split() if len(x)>2]
        rows=[]
        if SCAN_JSONL.exists():
            try:
                with SCAN_JSONL.open("r",encoding="utf-8",errors="ignore") as f:
                    for line in f:
                        if not line.strip(): continue
                        item=json.loads(line)
                        hay=(item.get("nome","")+" "+item.get("caminho","")).lower()
                        if not terms or any(t.lower() in hay for t in terms):
                            rows.append(item)
                            if len(rows)>=200: break
            except Exception: pass
        ctx["arquivos_relevantes"]=rows
    return ctx

def clean_agent_reply(text):
    text=str(text or "").strip()
    import re
    text=re.sub(r"<think>.*?</think>","",text,flags=re.I|re.S).strip()
    text=re.sub(r"^\s*(thinking|reasoning)\s*:.*?(?=\n\S|$)","",text,flags=re.I|re.S).strip()
    return text[:6000]

def best_checkpoint(prompt="", requested=""):
    """Escolhe apenas checkpoints reais e compatíveis com o pipeline nativo SD/SDXL."""
    choices=checkpoint_choices() if 'checkpoint_choices' in globals() else []
    if not choices:
        inv=inventory()
        choices=[x.get("relative") or x.get("name") for x in inv.get("files",[]) if x.get("category")=="checkpoints"]
    choices=[str(x) for x in choices if str(x).strip()]
    if not choices:return None, "Nenhum checkpoint encontrado."
    if requested and requested in choices:return requested, "selecionado pelo operador"
    low=str(prompt or "").lower()
    scored=[]
    for c in choices:
        n=Path(c).name.lower(); score=0
        arch=guess_architecture(n)
        # O workflow automático atual é SD/SDXL. Evita escolher FLUX/SD3 por engano.
        if arch=="SDXL": score+=50
        elif arch=="SD1.5": score+=20
        elif arch in {"FLUX","SD3"}: score-=50
        if any(k in low for k in ("retrato","portrait","pessoa","personagem","realista","realistic","foto","photoreal")):
            if any(k in n for k in ("realvis","juggernaut","realistic","dreamshaper")):score+=12
        if any(k in low for k in ("anime","manga","cartoon")) and any(k in n for k in ("pony","anime","anim")):score+=12
        scored.append((score,c))
    scored.sort(key=lambda x:(-x[0],x[1].lower()))
    return scored[0][1], f"melhor checkpoint real detectado ({guess_architecture(Path(scored[0][1]).name)})"

def agent_generation_plan(prompt,negative,choices):
    """Plano determinístico do AURION; não inventa modelos nem nomes de arquivos."""
    cp,_=best_checkpoint(prompt)
    if not cp:return {}
    arch=guess_architecture(Path(cp).name)
    # Não tenta usar um checkpoint FLUX/SD3 no workflow SDXL simples.
    if arch not in {"SDXL","SD1.5","checkpoint"}:
        compatible=[x for x in choices if guess_architecture(Path(x).name) in {"SDXL","SD1.5","checkpoint"}]
        if compatible:cp,_=best_checkpoint(prompt,compatible[0])
    arch=guess_architecture(Path(cp).name)
    if arch=="SD1.5":
        w,h,steps,cfg=768,768,28,7.0
    else:
        w,h,steps,cfg=1024,1024,30,6.5
    return {"checkpoint":cp,"width":w,"height":h,"steps":steps,"cfg":cfg,"reason":"AURION selecionou um checkpoint real compatível com o workflow."}

def agent_action(message):
    """Executa controles locais explícitos e seguros pedidos ao agente."""
    low=str(message or "").strip().lower()
    actions=[]
    if any(k in low for k in ("scan completo","scan completo do pc","escaneia tudo","varrer tudo","scan a-z","scan a:–z:")):
        if bg("Scan completo",complete_scan): return "AÇÃO EXECUTADA: scan completo iniciado em todos os discos, preservando arquivos."
        return "O scan não pôde iniciar porque outra operação pesada está em andamento."
    if any(k in low for k in ("scan local","escaneia local","scan meus arquivos")):
        if bg("Scan local",local_scan): return "AÇÃO EXECUTADA: scan local iniciado."
        return "O scan local não pôde iniciar porque outra operação pesada está em andamento."
    if any(k in low for k in ("ligue o comfy","inicie o comfy","iniciar comfy","comfyui ligar")):
        ok=start_comfy(); return "AÇÃO EXECUTADA: ComfyUI ONLINE." if ok else "AÇÃO FALHOU: não consegui colocar o ComfyUI ONLINE."
    if any(k in low for k in ("ligue o agente","inicie o agente","iniciar ollama","ligar ollama")):
        ok=start_ollama(); return "AÇÃO EXECUTADA: agente/Ollama ONLINE." if ok else "AÇÃO FALHOU: Ollama não respondeu."
    if any(k in low for k in ("refaça os slots","refazer slots","ligar modelos","reconfigurar modelos")):
        ok=bg("Configurar modelos",configure_comfy); return "AÇÃO EXECUTADA: slots de modelos sendo reconfigurados." if ok else "Outra operação pesada já está em andamento."
    if any(k in low for k in ("corrija tudo","corrigir tudo","consertar tudo","auto corrigir")):
        ok=bg("Correção completa",full_setup); return "AÇÃO EXECUTADA: correção completa iniciada." if ok else "Outra operação pesada já está em andamento."
    if any(k in low for k in ("atualize dependências","atualizar dependências","dependências")):
        ok=bg("Dependências",update_deps); return "AÇÃO EXECUTADA: verificação/atualização de dependências iniciada." if ok else "Outra operação pesada já está em andamento."
    if any(k in low for k in ("abrir comfy","abra o comfy")):
        webbrowser.open(COMFY_URL); return "AÇÃO EXECUTADA: ComfyUI aberto no navegador."
    if any(k in low for k in ("abrir webui","open webui","abra o webui")):
        webbrowser.open(OPENWEBUI_URL); return "AÇÃO EXECUTADA: Open WebUI aberto no navegador."
    if low in {"status","diagnóstico","diagnostico","como está o pc","status do pc"}:
        d=diagnose(light=True);return f"STATUS REAL: agente={d['ollama'].get('model') or 'OFFLINE'} | ComfyUI={'ONLINE' if d['comfy'].get('running') else 'OFFLINE'} | NVIDIA={'ONLINE' if d['nvidia'].get('gpus') else 'OFFLINE'} | modelos={d['models_inventory'].get('total',0)}"
    return None

def chat(message,model=None):
    if not port(OLLAMA_PORT):return None,"Ollama offline."
    model=model or choose_model()
    if not model:return None,"Nenhum modelo Ollama instalado."
    d=diagnose(True)
    scanctx=load_scan_summary_for_agent(message)
    memory=[]
    for folder in (MEMORY_DIR,MENTE_DIR,FRAG_DIR):
        if folder.exists():
            for p in sorted(folder.glob("*.md"),key=lambda x:x.stat().st_mtime if x.exists() else 0,reverse=True)[:20]:
                try: memory.append({"arquivo":p.name,"conteudo":p.read_text(encoding="utf-8",errors="replace")[:4000]})
                except Exception: pass
    history=load_chat_history()[-12:]
    system="""Você é o AGENTE AURION DYNAMIC LOCAL. Responda somente em português do Brasil. Seja direto e útil. Você é o agente operacional do painel: pode analisar o diagnóstico, o catálogo do scan, os modelos e a memória local. Nunca invente caminhos, modelos, arquivos ou ações concluídas. Quando o usuário pedir uma ação local, o AURION executa somente ações que o núcleo confirmou e informa o resultado real. Para informações sobre arquivos, use somente o SCAN REAL. Para serviços, use somente DIAGNÓSTICO LOCAL. Não mostre raciocínio interno, <think> ou cadeia de pensamento."""
    messages=[{"role":"system","content":system},
              {"role":"system","content":"DIAGNÓSTICO LOCAL:\n"+json.dumps(d,ensure_ascii=False,indent=2)},
              {"role":"system","content":"SCAN REAL:\n"+json.dumps(scanctx,ensure_ascii=False,indent=2)},
              {"role":"system","content":"MEMÓRIA LOCAL:\n"+json.dumps(memory,ensure_ascii=False,indent=2)},
              {"role":"system","content":"CÉREBRO/REGRAS APRENDIDAS:\n"+json.dumps(STATE["brain"],ensure_ascii=False,indent=2)}]
    for h in history:
        role=h.get("role") if h.get("role") in {"user","assistant"} else "user"
        messages.append({"role":role,"content":str(h.get("content") or "")[:6000]})
    messages.append({"role":"user","content":message})
    try:
        r=post_json(f"{OLLAMA_URL}/api/chat",{"model":model,"messages":messages,"stream":False,"keep_alive":"10m","options":{"temperature":0.2,"num_predict":700}},120)
        msg=((r.get("message") or {}).get("content") if isinstance(r,dict) else None)
        if not msg and isinstance(r,dict):msg=r.get("response")
        return clean_agent_reply(msg),None
    except Exception as e:
        log(f"Erro no chat Ollama: {e}",True);return None,str(e)

# ---------------- NVIDIA / CUDA ----------------
def nvidia():
    x=exe("nvidia-smi",[Path(r"C:\Windows\System32\nvidia-smi.exe"),Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")])
    if not x:return {"installed":False,"message":"nvidia-smi não encontrado."}
    try:
        p=subprocess.run([x,"--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=8,encoding="utf-8",errors="ignore")
        gs=[]
        for line in p.stdout.splitlines():
            a=[z.strip() for z in line.split(",")]
            if len(a)>=6:gs.append({"name":a[0],"driver":a[1],"vram_total_mb":a[2],"vram_used_mb":a[3],"gpu_percent":a[4],"temperature_c":a[5]})
        return {"installed":p.returncode==0,"executable":x,"gpus":gs,"raw":(p.stdout or p.stderr).strip()}
    except Exception as e:return {"installed":False,"message":str(e),"executable":x}
def cuda_py():
    try:
        p=subprocess.run([sys.executable,"-c","import torch; print('TORCH='+torch.__version__); print('CUDA='+str(torch.version.cuda)); print('AVAILABLE='+str(torch.cuda.is_available())); print('GPUS='+str(torch.cuda.device_count()))"],capture_output=True,text=True,timeout=15,encoding="utf-8",errors="ignore")
        return {"ok":p.returncode==0,"output":(p.stdout or p.stderr).strip()}
    except Exception as e:return {"ok":False,"output":str(e)}

def diagnose(light=False):
    c=comfy(); n=nvidia(); inv=inventory(); oll=port(OLLAMA_PORT)
    d={"timestamp":datetime.now().isoformat(timespec="seconds"),"project":str(PROJECT),"models":str(MODELS),"python":sys.version.split()[0],"python_executable":sys.executable,"comfy":c,"ollama":{"running":oll,"url":OLLAMA_URL,"port":OLLAMA_PORT,"executable":exe("ollama",[Path(os.environ.get("LOCALAPPDATA",""))/"Programs/Ollama/ollama.exe",Path(r"C:\Program Files\Ollama\ollama.exe")]),"model":choose_model() if oll else None},"openwebui":{"running":port(OPENWEBUI_PORT),"url":OPENWEBUI_URL,"port":OPENWEBUI_PORT,"executable":exe("open-webui")},"nvidia":n,"tools":{"git":exists("git"),"git_version":version(["git","--version"]) if exists("git") else "","ffmpeg":exists("ffmpeg"),"ffmpeg_version":version(["ffmpeg","-version"]) if exists("ffmpeg") else "","7zip":exists("7z") or exists("7za") or (DOWNLOADS/"7zr.exe").exists(),"winget":exists("winget")},"models_inventory":inv,"model_folders":model_folders()}
    if not light:d["cuda_python"]=cuda_py()
    return d

# ---------------- Git / dependencies / install ----------------
def git_root(p):
    if not exists("git") or not p.exists():return None
    try:
        q=subprocess.run(["git","-C",str(p),"rev-parse","--show-toplevel"],capture_output=True,text=True,timeout=10,encoding="utf-8",errors="ignore");o=q.stdout.strip();return Path(o) if q.returncode==0 and o else None
    except Exception:return None
def git_status(p):
    r=git_root(p)
    if not r:return {"path":str(p),"is_repo":False}
    def run(a):
        q=subprocess.run(["git","-C",str(r)]+a,capture_output=True,text=True,timeout=15,encoding="utf-8",errors="ignore");return (q.stdout or q.stderr).strip()
    branch=run(["branch","--show-current"])
    head=run(["rev-parse","--abbrev-ref","HEAD"])
    if head=="HEAD": branch="(DETACHED HEAD)"
    return {"path":str(r),"is_repo":True,"branch":branch,"head":run(["rev-parse","--short","HEAD"]),"detached":head=="HEAD","dirty":bool(run(["status","--porcelain"])),"status":run(["status","--short"]),"remote":run(["remote","-v"])}

def git_default_branch(r):
    # Primeiro tenta a referencia local origin/HEAD; depois consulta o remoto.
    for args in (["symbolic-ref","--short","refs/remotes/origin/HEAD"],):
        q=subprocess.run(["git","-C",str(r)]+args,capture_output=True,text=True,timeout=15,encoding="utf-8",errors="ignore")
        if q.returncode==0 and q.stdout.strip():
            v=q.stdout.strip()
            return v.split("origin/",1)[1] if v.startswith("origin/") else v
    q=subprocess.run(["git","-C",str(r),"ls-remote","--symref","origin","HEAD"],capture_output=True,text=True,timeout=30,encoding="utf-8",errors="ignore")
    for line in (q.stdout or "").splitlines():
        if line.startswith("ref:") and "refs/heads/" in line:
            return line.split("refs/heads/",1)[1].split("\t",1)[0].strip()
    for name in ("main","master"):
        q=subprocess.run(["git","-C",str(r),"show-ref","--verify",f"refs/remotes/origin/{name}"],capture_output=True,text=True,timeout=10,encoding="utf-8",errors="ignore")
        if q.returncode==0:return name
    return None

def git_repair_branch(r):
    r=Path(r)
    if not git_root(r):raise RuntimeError(f"Repositório Git não encontrado: {r}")
    status=git_status(r)
    if status.get("dirty"):
        raise RuntimeError("ComfyUI possui alterações locais. O AURION não fará checkout automático para não apagar trabalho local. Faça backup/commit/stash e tente novamente.")
    if not status.get("detached"):return status.get("branch") or ""
    log("Git em DETACHED HEAD. Corrigindo para a branch principal...")
    q=subprocess.run(["git","-C",str(r),"fetch","origin","--prune"],capture_output=True,text=True,timeout=300,encoding="utf-8",errors="ignore")
    out=((q.stdout or "")+"\n"+(q.stderr or "")).strip()
    for line in out.splitlines()[-60:]:log(line)
    if q.returncode:raise RuntimeError("git fetch origin falhou: "+(out[-1500:] or str(q.returncode)))
    branch=git_default_branch(r)
    if not branch:raise RuntimeError("Não foi possível descobrir a branch padrão do origin (main/master).")
    exists_local=subprocess.run(["git","-C",str(r),"show-ref","--verify",f"refs/heads/{branch}"],capture_output=True,timeout=10).returncode==0
    if exists_local:
        cmd=["git","-C",str(r),"checkout",branch]
    else:
        cmd=["git","-C",str(r),"checkout","-b",branch,"--track",f"origin/{branch}"]
    q=subprocess.run(cmd,capture_output=True,text=True,timeout=60,encoding="utf-8",errors="ignore")
    out=((q.stdout or "")+"\n"+(q.stderr or "")).strip()
    for line in out.splitlines()[-40:]:log(line)
    if q.returncode:raise RuntimeError("Não foi possível sair do DETACHED HEAD: "+(out[-2000:] or str(q.returncode)))
    log(f"Git reparado: branch {branch}")
    return branch
def repo_report():
    c=comfy();ps=[PROJECT]+configured_model_roots()
    if c["found"]:ps.append(Path(c["path"]))
    if c["found"] and (Path(c["path"])/"custom_nodes").exists():
        try:ps += [x for x in (Path(c["path"])/"custom_nodes").iterdir() if x.is_dir()]
        except OSError:pass
    out=[];seen=set()
    for p in ps:
        r=git_root(p)
        if r and str(r).lower() not in seen:seen.add(str(r).lower());out.append(git_status(r))
    return out
def git_pull(p):
    r=git_root(p)
    if not r:raise RuntimeError(f"Repositório não encontrado: {p}")
    git_repair_branch(r)
    q=subprocess.run(["git","-C",str(r),"pull","--ff-only"],capture_output=True,text=True,timeout=900,encoding="utf-8",errors="ignore")
    out=((q.stdout or "")+"\n"+(q.stderr or "")).strip()
    for line in out.splitlines()[-100:]:log(line)
    if q.returncode:raise RuntimeError(f"git pull falhou ({q.returncode}): {out[-2500:]}")
    log(f"Git atualizado com sucesso: {r}")
    return True
def update_all_git():
    done=0
    for r in repo_report():
        p=Path(r.get("path",""))
        if not p.exists() or not git_root(p):continue
        if r.get("dirty"):
            log(f"Git automático ignorado (alterações locais): {p}");continue
        try:git_pull(p);done+=1
        except Exception as e:log(f"Git automático falhou em {p}: {e}",True)
    log(f"Git automático: {done} repositório(s) atualizado(s).");return done

def update_comfy_git():
    c=comfy()
    if not c["found"]:raise RuntimeError("ComfyUI não encontrado.")
    return git_pull(Path(c["path"]))
def pip_install(py,args,cwd=None,timeout=1800):
    q=subprocess.run([str(py),"-m","pip","install","--upgrade"]+list(args),cwd=str(cwd) if cwd else None,
                     capture_output=True,text=True,timeout=timeout,encoding="utf-8",errors="ignore")
    out=((q.stdout or "")+"\n"+(q.stderr or "")).strip()
    for line in out.splitlines()[-40:]:log(line)
    return q.returncode==0,out

def update_deps():
    """Verifica/atualiza AURION, ComfyUI e requirements de custom_nodes."""
    targets=[];c=comfy()
    if c["found"]:
        targets.append((Path(c["python"]),Path(c["path"]),"ComfyUI"))
        cn=Path(c["path"])/"custom_nodes"
        if cn.exists():
            try:
                for node in cn.iterdir():
                    req=node/"requirements.txt"
                    if node.is_dir() and req.exists():targets.append((Path(c["python"]),node,node.name))
            except OSError:pass
    targets.append((Path(sys.executable),PROJECT,"AURION"))
    seen=set();errors=[]
    for py,cwd,label in targets:
        key=(str(py).lower(),str(cwd).lower())
        if key in seen or not py.exists():continue
        seen.add(key)
        try:
            ok,_=pip_install(py,["pip","setuptools","wheel"],cwd,900)
            if not ok:errors.append(f"{label}: pip base")
            req=cwd/"requirements.txt"
            if req.exists():
                ok,_=pip_install(py,["-r",str(req)],cwd,1800)
                if not ok:errors.append(f"{label}: requirements.txt")
                else:log(f"Dependências atualizadas: {label}")
        except Exception as e:errors.append(f"{label}: {e}");log(f"Dependências {label}: {e}",True)
    try:
        ok,_=pip_install(Path(sys.executable),["flask","pyyaml","huggingface_hub"],PROJECT,1200)
        if not ok:errors.append("AURION: pacotes mínimos")
    except Exception as e:errors.append(f"AURION mínimos: {e}")
    if errors:raise RuntimeError(" | ".join(errors))
    log("Todas as dependências detectadas foram verificadas/atualizadas.");return True

def maintenance_update_all():
    progress(10,"MANUTENÇÃO: verificando dependências...")
    try:update_deps()
    except Exception as e:log(f"Dependências: {e}",True)
    progress(55,"MANUTENÇÃO: conferindo modelos e slots...")
    configure_comfy();inventory(force=True)
    progress(75,"MANUTENÇÃO: conferindo repositórios...")
    try:update_all_git()
    except Exception as e:log(f"Git automático: {e}",True)
    progress(100,"Manutenção automática concluída.")

def download(url,dest,label):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 AURION"});dest.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(req,timeout=90) as r:
        total=int(r.headers.get("Content-Length","0") or 0);done=0
        with dest.open("wb") as f:
            while True:
                ch=r.read(1024*1024)
                if not ch:break
                f.write(ch);done+=len(ch)
                progress(int(done/total*100) if total else 0,f"{label}: {hsize(done)}"+(f" / {hsize(total)}" if total else ""))
    log(f"Download concluído: {dest}")
def install_comfy():
    if comfy()["found"]:log("ComfyUI já localizado.");return True
    arc=DOWNLOADS/"ComfyUI_windows_portable_nvidia.7z";seven=DOWNLOADS/"7zr.exe"
    if not arc.exists():download(COMFY_PORTABLE_URL,arc,"ComfyUI Portable NVIDIA")
    if not seven.exists():download(SEVENZIP_URL,seven,"7zr.exe")
    target=PROJECT/"ComfyUI_Portable";target.mkdir(parents=True,exist_ok=True)
    q=subprocess.run([str(seven),"x",str(arc),f"-o{target}","-y"],capture_output=True,text=True,timeout=3600,encoding="utf-8",errors="ignore")
    if q.returncode:log((q.stderr or "Falha na extração")[-3000:],True);return False
    return comfy()["found"]
def full_setup():
    log("=== CORREÇÃO COMPLETA ===");progress(5,"Verificando ComfyUI...")
    if not comfy()["found"]:
        progress(15,"ComfyUI não encontrado. Baixando...")
        if not install_comfy():raise RuntimeError("Não foi possível instalar/localizar ComfyUI.")
    progress(35,"Configurando modelos...");configure_comfy();inventory();progress(50,"Atualizando dependências...")
    try:update_deps()
    except Exception as e:log(f"Dependências: {e}",True)
    progress(75,"Atualizando Git do ComfyUI...")
    try:update_comfy_git()
    except Exception as e:log(f"Git ComfyUI: {e}",True)
    progress(100,"Correção completa finalizada.");log("=== CORREÇÃO COMPLETA FINALIZADA ===")

def startup():
    log("=== CARREGAMENTO INICIAL DO AURION ===")
    for name,fn in (("ollama",start_ollama),("comfyui",start_comfy),("openwebui",start_webui)):
        try:ok=fn()
        except Exception as e:ok=False;log(f"{name}: {e}",True)
        with LOCK:STATE["startup"][name]=ok
    with LOCK:STATE["startup_done"]=True
    log("=== SERVIÇOS INICIAIS FINALIZADOS ===")
    try:bg("Manutenção inicial",maintenance_update_all)
    except Exception as e:log(f"Manutenção inicial: {e}",True)

def open_cmd():
    try:subprocess.Popen(["cmd.exe","/d","/k"],cwd=str(PROJECT));log("CMD aberto.");return True
    except Exception as e:log(f"Erro CMD: {e}",True);return False

# ---------------- API ----------------
@app.get("/")
def index():return render_template_string(HTML)
@app.get("/api/status")
def api_status():
    d=diagnose()
    with LOCK:s={"busy":STATE["busy"],"operation":STATE["operation"],"progress":STATE["progress"],"message":STATE["message"],"logs":STATE["logs"][-100:],"errors":STATE["errors"][-60:],"agent_model":STATE.get("agent_model"),"startup_done":STATE["startup_done"],"startup":STATE["startup"],"scan":STATE.get("scan"),"image_job":STATE.get("image_job") }
    d["health"]=service_health()
    d["brain"]={"generations":len(STATE["brain"].get("generations",[])),"learned":STATE["brain"].get("learned",{}),"operator_notes":STATE["brain"].get("operator_notes","")}
    return jsonify({"diagnostics":d,"state":s})
@app.get("/api/diagnose")
def api_diag():return jsonify(diagnose())
@app.get("/api/models")
def api_models():return jsonify({"local":inventory(),"folders":model_folders(),"ollama":ollama_models(),"agent_model":choose_model() if port(OLLAMA_PORT) else None})
@app.post("/api/agent/model")
def api_agent_model():
    m=str((request.get_json(silent=True) or {}).get("model","")).strip();names=[x.get("name") for x in ollama_models()]
    if m not in names:return jsonify({"ok":False,"message":"Modelo Ollama não encontrado."}),404
    with LOCK:STATE["agent_model"]=m
    log(f"Agente carregado: {m}");return jsonify({"ok":True,"model":m})
def load_chat_history():
    try:
        if CHAT_FILE.exists():
            d=json.loads(CHAT_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d,list) else []
    except Exception:pass
    return []

def save_chat_history(items):
    try:
        CHAT_FILE.parent.mkdir(parents=True,exist_ok=True)
        CHAT_FILE.write_text(json.dumps(items[-200:],ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as e:log(f"Histórico do chat: {e}",True)

@app.get("/api/chat/history")
def api_chat_history():return jsonify({"ok":True,"messages":load_chat_history()[-200:]})

@app.post("/api/chat/clear")
def api_chat_clear():
    save_chat_history([]);return jsonify({"ok":True,"message":"Histórico do chat limpo."})

@app.post("/api/agent/action")
def api_agent_action():
    data=request.get_json(silent=True) or {};msg=str(data.get("message") or "").strip()
    if not msg:return jsonify({"ok":False,"message":"Ação vazia."}),400
    reply=agent_action(msg)
    return jsonify({"ok":bool(reply),"executed":bool(reply),"reply":reply or "Nenhuma ação operacional reconhecida; encaminhando para o chat."})

@app.post("/api/chat")
def api_chat():
    data=request.get_json(silent=True) or {};msg=str(data.get("message","")).strip();m=str(data.get("model","")).strip() or None
    if not msg:return jsonify({"reply":"Digite uma pergunta ou comando."})
    low=msg.lower()
    action_reply=agent_action(msg)
    if action_reply:
        reply=action_reply
    elif low in {"status","diagnostico","diagnóstico"}:
        d=diagnose();reply=f"AGENTE: {d['ollama']['model'] or 'não carregado'} | ComfyUI: {'ONLINE' if d['comfy']['running'] else 'OFFLINE'} | Ollama: {'ONLINE' if d['ollama']['running'] else 'OFFLINE'} | NVIDIA: {len(d['nvidia'].get('gpus',[]))} GPU(s) | Modelos: {d['models_inventory']['total']}"
    elif low in {"comfy","comfyui"}:
        c=comfy();reply=f"ComfyUI: {'encontrado' if c['found'] else 'não encontrado'} | {c.get('path') or '-'} | ONLINE={c['running']}"
    elif low=="modelos":
        i=inventory();reply=f"{i['total']} modelos locais — {i['size']}. Raízes catalogadas: {len(i['roots'])}"
    elif low in {"cuda","nvidia","gpu"}:reply=json.dumps(nvidia(),ensure_ascii=False,indent=2)
    elif low=="git":reply=json.dumps(repo_report(),ensure_ascii=False,indent=2)
    elif low in {"cmd","terminal"}:open_cmd();reply="CMD aberto."
    elif low in {"corrigir tudo","consertar","auto corrigir","autocorrigir"}:
        ok=bg("Correção solicitada pelo agente",full_setup);reply="Correção automática iniciada." if ok else "Outra operação já está em andamento."
    elif low in {"ligar modelos","configurar modelos","refazer slots"}:
        ok=bg("Configurar modelos",configure_comfy);reply="Slots de modelos reconfigurados." if ok else "Outra operação já está em andamento."
    else:
        ai,err=chat(msg,m);reply=ai or f"Agente indisponível: {err or 'erro desconhecido'}"
    chosen=STATE.get("agent_model") or m or choose_model()
    h=load_chat_history();h.append({"role":"user","content":msg,"time":datetime.now().isoformat(timespec="seconds")})
    h.append({"role":"assistant","content":reply,"model":chosen,"time":datetime.now().isoformat(timespec="seconds")});save_chat_history(h)
    return jsonify({"reply":reply,"model":chosen})

@app.get("/api/config")
def api_config_get():load_config();return jsonify(CONFIG)
@app.post("/api/config")
def api_config_post():
    data=request.get_json(silent=True) or {};save_config(data);log("Configuração salva.");return jsonify({"ok":True,"config":CONFIG,"message":"Configuração salva."})
def huggingface_update():
    repos=[str(x).strip() for x in (CONFIG.get("huggingface_repos") or []) if str(x).strip()]
    if not repos:return []
    try:from huggingface_hub import snapshot_download
    except Exception as e:return [{"ok":False,"message":str(e)}]
    out=[];root=PROJECT/"huggingface";root.mkdir(parents=True,exist_ok=True)
    for repo in repos:
        try:
            dest=root/repo.replace("/","__").replace("\\","__").replace(":","_");snapshot_download(repo_id=repo,local_dir=str(dest));out.append({"ok":True,"repo_id":repo,"path":str(dest)});log(f"Hugging Face sincronizado: {repo}")
        except Exception as e:out.append({"ok":False,"repo_id":repo,"message":str(e)});log(f"Hugging Face falhou: {repo}: {e}",True)
    return out
@app.post("/api/huggingface/update")
def api_hf_update():return (jsonify({"ok":True}) if bg("Hugging Face",huggingface_update) else (jsonify({"ok":False}),409))
@app.get("/api/automation")
def api_automation():
    with LOCK:a=json.loads(json.dumps(STATE["automation"],ensure_ascii=False))
    return jsonify({"ok":True,"automation":a,"brain":STATE["brain"]})
@app.post("/api/automation")
def api_automation_set():
    data=request.get_json(silent=True) or {};enabled=bool(data.get("enabled",True))
    with LOCK:STATE["automation"]["enabled"]=enabled
    automation_action("Automação "+("ATIVADA" if enabled else "PAUSADA")+" pelo operador.")
    return jsonify({"ok":True,"enabled":enabled,"message":"Automação "+("ativada." if enabled else "pausada.")})
@app.post("/api/agent/learn")
def api_agent_learn():
    data=request.get_json(silent=True) or {};note=str(data.get("note") or data.get("text") or "").strip()
    if not note:return jsonify({"ok":False,"message":"Escreva uma preferência."}),400
    brain_event("learned",{"ultima_preferencia":note,"atualizado":datetime.now().isoformat(timespec="seconds")});return jsonify({"ok":True,"message":"Preferência aprendida e salva."})
def service_health():
    out={"ollama":False,"comfy":False,"openwebui":False,"nvidia":False}
    out["ollama"]=bool(port(OLLAMA_PORT) and isinstance(http_json(f"{OLLAMA_URL}/api/tags",4),dict))
    out["comfy"]=bool(port(COMFY_PORT) and isinstance(http_json(f"{COMFY_URL}/system_stats",4),dict))
    try:
        with urllib.request.urlopen(OPENWEBUI_URL,timeout=4) as r:out["openwebui"]=r.status<500
    except Exception:pass
    out["nvidia"]=bool(nvidia().get("gpus"));return out
def automation_action(msg):
    with LOCK:
        a=STATE["automation"];a["last_check"]=datetime.now().isoformat(timespec="seconds");a["actions"]=(a.get("actions",[])+[f"[{datetime.now():%H:%M:%S}] {msg}"])[-100:]
def autonomous_supervisor():
    last=0;log("Cérebro autônomo: monitoramento ATIVO.")
    while True:
        try:
            if STATE["automation"].get("enabled",True):
                h=service_health()
                if not h["ollama"] and start_ollama():automation_action("Ollama religado automaticamente.")
                if not h["comfy"] and start_comfy():automation_action("ComfyUI religado automaticamente.")
                now=time.time()
                if now-last>=MAINTENANCE_INTERVAL and not STATE.get("busy"):
                    try:
                        maintenance_update_all()
                        automation_action("Dependências, slots, catálogo e Git verificados automaticamente.")
                    except Exception as e:log(f"Manutenção autônoma: {e}",True)
                    last=now
                    with LOCK:STATE["automation"]["last_maintenance"]=datetime.now().isoformat(timespec="seconds")
        except Exception as e:log(f"Supervisor: {e}",True)
        time.sleep(AUTOMATION_INTERVAL)
@app.post("/api/setup")
def api_setup():return (jsonify({"ok":True,"message":"Correção completa iniciada."}) if bg("Correção completa",full_setup) else (jsonify({"ok":False,"message":"Outra operação já está em andamento."}),409))
@app.post("/api/restart-services")
def api_restart():return (jsonify({"ok":True}) if bg("Recarregar serviços",startup) else (jsonify({"ok":False}),409))
@app.post("/api/start/<service>")
def api_start(service):
    fn={"comfy":start_comfy,"ollama":start_ollama,"openwebui":start_webui}.get(service)
    if not fn:return jsonify({"ok":False}),404
    return (jsonify({"ok":True}) if bg("Iniciar "+service,fn) else (jsonify({"ok":False}),409))
@app.post("/api/open/<service>")
def api_open(service):
    u={"comfy":COMFY_URL,"ollama":OLLAMA_URL,"openwebui":OPENWEBUI_URL,"panel":f"http://{HOST}:{PORT}"}.get(service)
    if not u:return jsonify({"ok":False}),404
    webbrowser.open(u);log(f"Abrindo {service}: {u}");return jsonify({"ok":True})
@app.post("/api/cmd")
def api_cmd():return jsonify({"ok":open_cmd()})
@app.post("/api/configure-models")
def api_cfg():
    def job():
        configure_comfy();inventory(force=True);log("Slots refeitos. O ComfyUI precisa ser reiniciado para reler os caminhos externos.")
    return (jsonify({"ok":True,"message":"Slots refeitos; reinicie/recarregue o ComfyUI para aplicar."}) if bg("Configurar modelos",job) else (jsonify({"ok":False,"message":"Outra operação já está em andamento."}),409))
@app.post("/api/dependencies")
def api_dep():return (jsonify({"ok":True}) if bg("Dependências",update_deps) else (jsonify({"ok":False}),409))
@app.post("/api/download-comfy")
def api_down():return (jsonify({"ok":True}) if bg("Baixar ComfyUI",install_comfy) else (jsonify({"ok":False}),409))
@app.post("/api/git/comfy-update")
def api_git_comfy():return (jsonify({"ok":True}) if bg("Atualizar ComfyUI via Git",update_comfy_git) else (jsonify({"ok":False}),409))
@app.post("/api/git/update")
def api_git_update():
    p=Path(str(request.args.get("path") or PROJECT))
    return (jsonify({"ok":True}) if bg("Git Pull",git_pull,p) else (jsonify({"ok":False}),409))
@app.get("/api/git")
def api_git():return jsonify({"repos":repo_report(),"project":git_status(PROJECT)})
@app.get("/api/comfy/stats")
def api_stats():
    x=comfy_stats()
    if x is None:return jsonify({"ok":False,"message":"ComfyUI offline."}),503
    return jsonify({"ok":True,"stats":x})
@app.post("/api/comfy/queue")
def api_queue():
    data=request.get_json(silent=True) or {};text=str(data.get("workflow","")).strip()
    if not text:return jsonify({"ok":False,"message":"Cole o workflow/API JSON do ComfyUI."}),400
    if not port(COMFY_PORT):return jsonify({"ok":False,"message":"ComfyUI offline."}),503
    try:
        wf=json.loads(text)
        if not isinstance(wf,dict):raise ValueError("O JSON precisa ser um objeto.")
        # O endpoint /prompt aceita o formato API: {node_id: {class_type, inputs}}.
        # Se o usuário colar o JSON já encapsulado, preservamos o campo prompt.
        if "prompt" in wf and isinstance(wf.get("prompt"),dict):
            payload=wf
        elif "nodes" in wf and "links" in wf:
            raise ValueError("Você colou o workflow visual do ComfyUI. Exporte pelo menu 'Save (API Format)' e cole o JSON API aqui.")
        elif all(isinstance(v,dict) and "class_type" in v for v in wf.values()):
            payload={"prompt":wf}
        else:
            raise ValueError("Formato não reconhecido. Use o JSON exportado em 'Save (API Format)' no ComfyUI.")
        r=post_json(f"{COMFY_URL}/prompt",payload,60)
        log(f"Workflow enviado ao ComfyUI: {r}")
        return jsonify({"ok":True,"result":r})
    except Exception as e:
        log(f"Workflow inválido/falha: {type(e).__name__}: {e}",True)
        return jsonify({"ok":False,"message":str(e)}),500 if "HTTP " in str(e) else 400

# ---------------- Memória / MENTE ----------------
def safe_filename(name,default="memoria"):
    name=str(name or "").strip() or default
    keep="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ."
    name="".join(c if c in keep else "_" for c in name).strip(" ._") or default
    return name if name.lower().endswith(".md") else name+".md"

def list_memory_files():
    out=[]
    for folder,label in ((MEMORY_DIR,"memoria"),(MENTE_DIR,"mente"),(FRAG_DIR,"fragmentos")):
        if not folder.exists(): continue
        for p in folder.glob("*.md"):
            try: out.append({"name":p.name,"path":str(p),"category":label,"size":p.stat().st_size,"modified":datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M")})
            except OSError: pass
    return sorted(out,key=lambda x:x["modified"],reverse=True)

def comfy_checkpoint_choices():
    if not port(COMFY_PORT): return []
    d=http_json(f"{COMFY_URL}/object_info",15)
    try:
        vals=d["CheckpointLoaderSimple"]["input"] ["required"]["ckpt_name"][0]
        return [str(x) for x in vals if x]
    except Exception: return []

def comfy_node_exists(name):
    d=http_json(f"{COMFY_URL}/object_info",10) or {}
    return isinstance(d,dict) and name in d

def build_sdxl_workflow(prompt,negative,checkpoint,width,height,steps,cfg,seed,lora="",vae="",controlnet="",control_image=""):
    if seed<0:seed=int(time.time()*1000)%2147483647
    wf={
      "3":{"class_type":"KSampler","inputs":{"seed":seed,"steps":steps,"cfg":cfg,"sampler_name":"euler","scheduler":"normal","denoise":1.0,"model":["4",0],"positive":["6",0],"negative":["7",0],"latent_image":["5",0]}},
      "4":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":checkpoint}},
      "5":{"class_type":"EmptyLatentImage","inputs":{"width":width,"height":height,"batch_size":1}},
      "6":{"class_type":"CLIPTextEncode","inputs":{"text":prompt,"clip":["4",1]}},
      "7":{"class_type":"CLIPTextEncode","inputs":{"text":negative,"clip":["4",1]}},
      "8":{"class_type":"VAEDecode","inputs":{"samples":["3",0],"vae":["4",2]}},
      "9":{"class_type":"SaveImage","inputs":{"filename_prefix":"AURION","images":["8",0]}}
    }
    if lora:
        if not comfy_node_exists("LoraLoader"):raise RuntimeError("O ComfyUI não possui LoraLoader.")
        wf["10"]={"class_type":"LoraLoader","inputs":{"model":["4",0],"clip":["4",1],"lora_name":lora,"strength_model":1.0,"strength_clip":1.0}}
        wf["3"]["inputs"]["model"]=["10",0];wf["6"]["inputs"]["clip"]=["10",1];wf["7"]["inputs"]["clip"]=["10",1]
    if vae:
        if not comfy_node_exists("VAELoader"):raise RuntimeError("O ComfyUI não possui VAELoader.")
        wf["11"]={"class_type":"VAELoader","inputs":{"vae_name":vae}};wf["8"]["inputs"]["vae"]=["11",0]
    if controlnet:
        if not control_image:raise RuntimeError("Selecione uma imagem de referência para usar ControlNet.")
        if not comfy_node_exists("ControlNetLoader") or not comfy_node_exists("ControlNetApplyAdvanced"):
            raise RuntimeError("Os nós de ControlNet necessários não estão disponíveis.")
        wf["12"]={"class_type":"LoadImage","inputs":{"image":control_image}}
        wf["13"]={"class_type":"ControlNetLoader","inputs":{"control_net_name":controlnet}}
        wf["14"]={"class_type":"ControlNetApplyAdvanced","inputs":{"positive":["6",0],"negative":["7",0],"control_net":["13",0],"image":["12",0],"strength":1.0,"start_percent":0.0,"end_percent":1.0}}
        wf["3"]["inputs"]["positive"]=["14",0];wf["3"]["inputs"]["negative"]=["14",1]
    return wf

def comfy_history(prompt_id):
    return http_json(f"{COMFY_URL}/history/{prompt_id}",5)

def extract_history_images(hist):
    found=[]
    if not isinstance(hist,dict): return found
    for item in hist.values():
        outputs=item.get("outputs",{}) if isinstance(item,dict) else {}
        for node in outputs.values():
            for img in node.get("images",[]) if isinstance(node,dict) else []:
                if isinstance(img,dict) and img.get("filename"):
                    found.append(img)
    return found

@app.get("/api/memory/list")
def api_memory_list(): return jsonify({"ok":True,"files":list_memory_files()})
@app.post("/api/memory/save")
def api_memory_save():
    data=request.get_json(silent=True) or {}; title=safe_filename(data.get("title")); content=str(data.get("content") or "").strip()
    if not content:return jsonify({"ok":False,"message":"Digite o conteúdo da memória."}),400
    path=MEMORY_DIR/title; path.write_text(content,encoding="utf-8"); log(f"Memória salva: {path.name}"); return jsonify({"ok":True,"path":str(path),"message":"Memória salva."})
@app.post("/api/memory/load")
def api_memory_load():
    data=request.get_json(silent=True) or {}; raw=str(data.get("path") or "");
    if not raw:return jsonify({"ok":False,"message":"Caminho não informado."}),400
    try: path=Path(raw).resolve(); path.relative_to(PROJECT.resolve())
    except Exception:return jsonify({"ok":False,"message":"Arquivo fora da base do AURION."}),403
    if not path.exists() or not path.is_file():return jsonify({"ok":False,"message":"Memória não encontrada."}),404
    return jsonify({"ok":True,"path":str(path),"content":path.read_text(encoding="utf-8",errors="replace")[:200000]})
@app.post("/api/agent/load")
def api_agent_load():
    data=request.get_json(silent=True) or {}; requested=str(data.get("model") or "").strip()
    if not start_ollama():return jsonify({"ok":False,"message":"Ollama não está disponível."}),503
    names=[x.get("name") for x in ollama_models() if x.get("name")]
    model=requested if requested in names else choose_model()
    if not model:return jsonify({"ok":False,"message":"Nenhum modelo Ollama encontrado."}),404
    with LOCK: STATE["agent_model"]=model
    try:
        post_json(f"{OLLAMA_URL}/api/generate",{"model":model,"prompt":"Responda apenas OK.","stream":False,"keep_alive":"10m","options":{"num_predict":2,"temperature":0}},30)
        log(f"Agente carregado e aquecido: {model}"); return jsonify({"ok":True,"model":model,"message":f"Agente carregado: {model}"})
    except Exception as e:log(f"Falha ao aquecer agente: {e}",True);return jsonify({"ok":False,"message":str(e)}),500

def comfy_object_choices(node,field):
    if not port(COMFY_PORT):return []
    d=http_json(f"{COMFY_URL}/object_info",15) or {}
    try:return [str(x) for x in d[node]["input"]["required"][field][0] if x]
    except Exception:return []
def checkpoint_choices():
    inv=inventory();fs=[x for x in inv["files"] if x["category"]=="checkpoints"]
    comfy_names=comfy_object_choices("CheckpointLoaderSimple","ckpt_name")
    out=[];seen=set()
    for x in comfy_names+[x["relative"] for x in fs]+[x["name"] for x in fs]:
        x=str(x)
        if x and x.lower() not in seen:seen.add(x.lower());out.append(x)
    return out

def slot_choices(category):
    inv=inventory();fs=[x for x in inv["files"] if x["category"]==category]
    out=[];seen=set()
    for x in fs:
        for val in (x.get("relative"),x.get("name")):
            val=str(val or "")
            if val and val.lower() not in seen:seen.add(val.lower());out.append(val)
    return out

@app.get("/api/image/options")
def api_image_options():
    inv=inventory();cp=checkpoint_choices()
    return jsonify({"ok":True,"running":port(COMFY_PORT),"checkpoints":cp,"slots":{
        "checkpoints":cp,"loras":slot_choices("loras"),"vae":slot_choices("vae"),"controlnet":slot_choices("controlnet"),
        "diffusion_models":slot_choices("diffusion_models"),"text_encoders":slot_choices("text_encoders")},
        "counts":inv["categories"],"roots":inv["roots"]})

@app.post("/api/image/upload")
def api_image_upload():
    f=request.files.get("file")
    if not f or not f.filename:return jsonify({"ok":False,"message":"Nenhuma imagem enviada."}),400
    ext=Path(f.filename).suffix.lower()
    if ext not in {".png",".jpg",".jpeg",".webp",".bmp"}:return jsonify({"ok":False,"message":"Formato não suportado."}),400
    up=PROJECT/"_uploads";up.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(f.filename).name);dest=up/f"{int(time.time()*1000)}_{safe}";f.save(dest)
    c=comfy()
    if not c.get("found"):return jsonify({"ok":False,"message":"ComfyUI não encontrado."}),503
    inp=Path(c["path"])/"input";inp.mkdir(parents=True,exist_ok=True);target=inp/dest.name;shutil.copy2(dest,target)
    log(f"Imagem de referência recebida: {dest.name}");return jsonify({"ok":True,"name":dest.name,"comfy_name":dest.name,"path":str(dest)})

@app.post("/api/image/advice")
def api_image_advice():
    data=request.get_json(silent=True) or {};p=str(data.get("prompt") or "").strip();neg=str(data.get("negative") or "")
    choices=checkpoint_choices()
    if not choices:return jsonify({"ok":False,"message":"Nenhum checkpoint real encontrado. Refaça os slots e recarregue o ComfyUI."}),404
    plan=agent_generation_plan(p,neg,choices)
    if not plan:
        cp,_=best_checkpoint(p,str(data.get("checkpoint") or ""));plan={"checkpoint":cp,"width":1024,"height":1024,"steps":24,"cfg":6.5,"reason":"fallback AURION"}
    return jsonify({"ok":True,"plan":plan,"model":STATE.get("agent_model")})

@app.post("/api/image/generate")
def api_image_generate():
    data=request.get_json(silent=True) or {};prompt=str(data.get("prompt") or "").strip()
    negative=str(data.get("negative") or "low quality, blurry, distorted, duplicate, watermark").strip()
    if not prompt:return jsonify({"ok":False,"message":"Digite o prompt da imagem."}),400
    if not port(COMFY_PORT):return jsonify({"ok":False,"message":"ComfyUI offline."}),503
    choices=checkpoint_choices()
    if not choices:return jsonify({"ok":False,"message":"Nenhum checkpoint foi encontrado pelo ComfyUI/catalogador."}),400
    requested=str(data.get("checkpoint") or "").strip();auto=str(data.get("auto_agent","true")).lower() not in {"0","false","off","nao","não"}
    plan=agent_generation_plan(prompt,negative,choices) if auto else {}
    checkpoint=requested if requested in choices else (plan.get("checkpoint") if plan.get("checkpoint") in choices else best_checkpoint(prompt)[0])
    if not checkpoint:return jsonify({"ok":False,"message":"Nenhum checkpoint selecionável."}),400
    try:
        width=max(256,min(2048,int(plan.get("width",data.get("width",1024)))));height=max(256,min(2048,int(plan.get("height",data.get("height",1024)))))
        steps=max(1,min(100,int(plan.get("steps",data.get("steps",28)))));cfg=max(.1,min(30,float(str(plan.get("cfg",data.get("cfg",7))).replace(",","."))));seed=int(data.get("seed",-1))
    except Exception:return jsonify({"ok":False,"message":"Parâmetros inválidos."}),400
    lora=str(data.get("lora") or "").strip();vae=str(data.get("vae") or "").strip();controlnet=str(data.get("controlnet") or "").strip();control_image=str(data.get("control_image") or "").strip()
    try:
        wf=build_sdxl_workflow(prompt,negative,checkpoint,width,height,steps,cfg,seed,lora,vae,controlnet,control_image)
        client_id=f"aurion-{int(time.time()*1000)}";r=post_json(f"{COMFY_URL}/prompt",{"prompt":wf,"client_id":client_id},60);pid=r.get("prompt_id") if isinstance(r,dict) else None
        if not pid:return jsonify({"ok":False,"message":"ComfyUI recusou o workflow.","detail":json.dumps(r,ensure_ascii=False)[:6000],"result":r}),500
        with LOCK:STATE["image_job"]={"prompt_id":pid,"client_id":client_id,"prompt":prompt,"started":time.time(),"steps":steps,"checkpoint":checkpoint,"agent_plan":plan,"lora":lora,"vae":vae,"controlnet":controlnet}
        brain_event("generation",{"time":datetime.now().isoformat(timespec="seconds"),"prompt":prompt,"checkpoint":checkpoint,"steps":steps,"cfg":cfg,"width":width,"height":height,"agent_plan":plan,"lora":lora,"vae":vae,"controlnet":controlnet})
        log(f"Geração iniciada: {pid} | {checkpoint} | agente={'ON' if auto else 'OFF'}")
        return jsonify({"ok":True,"prompt_id":pid,"client_id":client_id,"steps":steps,"checkpoint":checkpoint,"agent_plan":plan})
    except Exception as e:log(f"Falha ao iniciar geração: {e}",True);return jsonify({"ok":False,"message":str(e)}),500

@app.post("/api/image/cancel/<prompt_id>")
def api_image_cancel(prompt_id):
    if not port(COMFY_PORT):return jsonify({"ok":False,"message":"ComfyUI offline."}),503
    try:
        r=post_json(f"{COMFY_URL}/queue",{"delete":[prompt_id]},20)
        with LOCK:
            if STATE.get("image_job",{}).get("prompt_id")==prompt_id:STATE["image_job"]={**STATE["image_job"],"cancelled":True}
        log(f"Geração cancelada: {prompt_id}");return jsonify({"ok":True,"result":r})
    except Exception as e:return jsonify({"ok":False,"message":str(e)}),500

@app.get("/api/image/progress/<prompt_id>")
def api_image_progress(prompt_id):
    hist=comfy_history(prompt_id)
    if isinstance(hist,dict) and prompt_id in hist:
        item=hist.get(prompt_id) or {};si=item.get("status",{}) if isinstance(item,dict) else {}
        status_str=str(si.get("status_str") or si.get("status") or "concluido");msgs=si.get("messages",[]) if isinstance(si,dict) else [];error_text=""
        if isinstance(msgs,list):
            for m in msgs[-20:]:
                if isinstance(m,(list,tuple)) and len(m)>1 and "error" in str(m[0]).lower():error_text=str(m[1])
        imgs=extract_history_images(hist)
        if si.get("completed") or imgs:
            with LOCK:STATE["image_job"]={**STATE.get("image_job",{}),"done":True,"progress":100,"images":imgs}
            return jsonify({"ok":True,"status":"concluido","progress":100,"images":imgs,"history":hist})
        if "error" in status_str.lower() or error_text:return jsonify({"ok":False,"status":"erro","progress":100,"images":[],"message":error_text or status_str,"history":hist})
    q=http_json(f"{COMFY_URL}/queue",5) or {};running=q.get("queue_running",[]) if isinstance(q,dict) else [];pending=q.get("queue_pending",[]) if isinstance(q,dict) else []
    def has_pid(items):return any(isinstance(x,list) and len(x)>1 and str(x[1])==prompt_id for x in items)
    status="executando" if has_pid(running) else "fila" if has_pid(pending) else "processando"
    with LOCK:job=STATE.get("image_job",{}).copy()
    elapsed=max(0,time.time()-float(job.get("started",time.time())));steps=int(job.get("steps",28));pct=min(95,int((elapsed/max(8,steps*2.2))*95))
    if elapsed>max(1800,steps*60) and not has_pid(running) and not has_pid(pending):status="tempo limite / aguardando histórico"
    return jsonify({"ok":True,"status":status,"progress":pct,"elapsed":round(elapsed,1),"images":[],"checkpoint":job.get("checkpoint"),"agent_plan":job.get("agent_plan",{})})

# ---------------- Scan / organização ----------------
SCAN_EXT={
    "codigo": {".py",".js",".ts",".jsx",".tsx",".ps1",".bat",".cmd",".sh",".cpp",".c",".h",".hpp",".java",".cs"},
    "imagem": {".png",".jpg",".jpeg",".webp",".bmp",".gif",".tif",".tiff",".psd",".ai",".svg"},
    "video": {".mp4",".mov",".mkv",".avi",".webm",".m4v",".mts"},
    "audio": {".mp3",".wav",".flac",".ogg",".m4a",".aac"},
    "documento": {".pdf",".doc",".docx",".txt",".md",".rtf",".odt"},
    "planilha": {".xlsx",".xls",".csv",".ods"},
    "projeto": {".aep",".aet",".c4d",".blend",".prproj",".drp",".fcpxml",".psd",".ai"},
    "workflow": {".json",".yaml",".yml",".workflow"},
    "modelo": MODEL_EXT,
}
CLIENT_HINTS=("cliente","clientes","client","clients","tomim","banda","marca","empresa","contrato","orcamento","orçamento")
PROJECT_HINTS=("projeto","projetos","project","projects","job","jobs","campanha","campanhas","video","vídeo","clipe","clip","animfruts","frutinhas","storyboard","render","3d","ensaio","fotografia","foto")
IGNORE_SCAN=IGNORE | {"cache","temp","tmp","__pycache__","venv",".venv","dist","build"}

def classify_path(path: Path, root: Path, is_dir=False):
    text=" ".join(path.parts).lower()
    name=path.name.lower()
    ext=path.suffix.lower()
    if is_dir:
        if any(k in text for k in CLIENT_HINTS): return "cliente"
        if any(k in text for k in PROJECT_HINTS): return "projeto"
        return "pasta"
    for cat,exts in SCAN_EXT.items():
        if ext in exts: return cat
    if name.startswith("client_") or "cliente" in text: return "cliente"
    return "outro"

def scan_roots(roots,label="SCAN"):
    result={"timestamp":datetime.now().isoformat(timespec="seconds"),"label":label,"arquivos":0,"pastas":0,"bytes":0,"por_tipo":{},"alvos":[],
            "clientes":{},"projetos":{},"repositorios":[],"arquivos_destaque":[],"erros":[],"catalogo_completo":False}
    seen_roots=set();top=[];client_dirs=[];project_dirs=[];root_names={"clientes","cliente","clients","client","projetos","projeto","projects","project"}
    SCAN_DIR.mkdir(parents=True,exist_ok=True)
    try:SCAN_JSONL.unlink(missing_ok=True)
    except Exception:pass
    def register(bucket,name,path,confidence=85):
        path=path.resolve();d=result[bucket].setdefault(name,{"pasta":str(path),"arquivos":0,"bytes":0,"tipo":bucket[:-1],"confianca":confidence});d["confianca"]=max(d.get("confianca",0),confidence);return path
    for root in roots:
        try:root=root.resolve()
        except Exception:continue
        if not root.exists():continue
        key=str(root).lower()
        if key in seen_roots:continue
        seen_roots.add(key);result["alvos"].append(str(root))
        for cur,dirs,files in os.walk(root,topdown=True):
            curp=Path(cur);dirs[:]=[d for d in dirs if d not in IGNORE_SCAN and not d.startswith(".") and not ((curp.parent == curp) and d.lower() in {"windows","program files","program files (x86)","programdata","$recycle.bin","system volume information","recovery"})];result["pastas"]+=len(dirs)
            if (curp/".git").is_dir():result["repositorios"].append(str(curp))
            lowcur=curp.name.lower()
            if lowcur in {"clientes","cliente","clients","client"}:
                for d in dirs:client_dirs.append((register("clientes",d,curp/d,98),d))
            if lowcur in {"projetos","projeto","projects","project"}:
                for d in dirs:project_dirs.append((register("projetos",d,curp/d,98),d))
            for d in dirs:
                dp=curp/d;ld=d.lower()
                if any(k in ld for k in CLIENT_HINTS):client_dirs.append((register("clientes",d,dp,90),d))
                if any(k in ld for k in PROJECT_HINTS):project_dirs.append((register("projetos",d,dp,82),d))
            for fn in files:
                fp=curp/fn
                try:size=fp.stat().st_size
                except (OSError,PermissionError) as e:result["erros"].append(f"{fp}: {e}");continue
                result["arquivos"]+=1;result["bytes"]+=size
                if result["arquivos"]%1000==0:progress(min(95,5+result["arquivos"]//1000),f"{label}: {result['arquivos']} arquivos indexados...")
                cat=classify_path(fp,root);result["por_tipo"][cat]=result["por_tipo"].get(cat,0)+1;fpr=fp.resolve();associations=[]
                for ep,name in client_dirs:
                    try:fpr.relative_to(ep);result["clientes"][name]["arquivos"]+=1;result["clientes"][name]["bytes"]+=size;associations.append({"tipo":"cliente","nome":name})
                    except ValueError:pass
                for ep,name in project_dirs:
                    try:fpr.relative_to(ep);result["projetos"][name]["arquivos"]+=1;result["projetos"][name]["bytes"]+=size;associations.append({"tipo":"projeto","nome":name})
                    except ValueError:pass
                if fp.suffix.lower() in SCAN_EXT["projeto"] or fp.suffix.lower() in SCAN_EXT["workflow"]:
                    parent=fp.parent
                    if parent.name.lower() not in root_names and len(parent.name)>1:
                        pname=parent.name;register("projetos",pname,parent,65);result["projetos"][pname]["arquivos"]+=1;result["projetos"][pname]["bytes"]+=size
                        if not any(a["tipo"]=="projeto" and a["nome"]==pname for a in associations):associations.append({"tipo":"projeto","nome":pname})
                row={"nome":fn,"caminho":str(fp),"tipo":cat,"bytes":size,"tamanho":hsize(size),"ext":fp.suffix.lower(),"clientes":[a["nome"] for a in associations if a["tipo"]=="cliente"],"projetos":[a["nome"] for a in associations if a["tipo"]=="projeto"]}
                try:
                    with SCAN_JSONL.open("a",encoding="utf-8") as jf:jf.write(json.dumps(row,ensure_ascii=False)+"\n")
                except Exception as e:result["erros"].append(f"JSONL {fp}: {e}")
                top.append(row);top.sort(key=lambda x:x["bytes"],reverse=True);del top[500:]
    result["tamanho"]=hsize(result["bytes"]);result["clientes"]=dict(sorted(result["clientes"].items(),key=lambda x:(-x[1]["arquivos"],x[0].lower())))
    result["projetos"]=dict(sorted(result["projetos"].items(),key=lambda x:(-x[1]["arquivos"],x[0].lower())));result["arquivos_destaque"]=top
    result["catalogo_completo"]=True;result["catalogo_arquivo"]=str(SCAN_JSONL);result["catalogo_registros"]=result["arquivos"]
    try:SCAN_REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as e:result["erros"].append(f"Não foi possível salvar relatório: {e}")
    return result

def local_scan():
    home=Path.home()
    roots=[PROJECT,home/"Desktop",home/"Documents",home/"Downloads",home/"OneDrive",Path(r"C:\COMFYUI")]
    return scan_roots(roots,"LOCAL")

def complete_scan():
    # Varre todos os discos disponíveis, mas poda áreas do Windows que só geram ruído/atraso.
    drives=[Path(f"{x}:\\") for x in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{x}:\\").exists()]
    return scan_roots(drives,"COMPLETO")

@app.post("/api/scan")
def api_scan():
    def job():
        progress(5,"SCAN LOCAL: indexando projetos, clientes e arquivos...")
        r=local_scan()
        with LOCK: STATE["scan"]=r
        progress(100,f"Scan local finalizado: {r['arquivos']} arquivos.")
        log(f"Scan local: {r['arquivos']} arquivos | {len(r['clientes'])} clientes | {len(r['projetos'])} projetos")
    return (jsonify({"ok":True,"message":"Scan local iniciado."}) if bg("Scan local",job) else (jsonify({"ok":False,"message":"Outra operação já está em andamento."}),409))

@app.post("/api/scan-completo")
def api_scan_completo():
    def job():
        progress(2,"SCAN COMPLETO: examinando discos...")
        r=complete_scan()
        with LOCK: STATE["scan"]=r
        progress(100,f"Scan completo finalizado: {r['arquivos']} arquivos.")
        log(f"Scan completo: {r['arquivos']} arquivos | {len(r['clientes'])} clientes | {len(r['projetos'])} projetos")
    return (jsonify({"ok":True,"message":"Scan completo iniciado."}) if bg("Scan completo",job) else (jsonify({"ok":False,"message":"Outra operação já está em andamento."}),409))

@app.get("/api/scan/report")
def api_scan_report():
    if not SCAN_REPORT.exists(): return jsonify({"ok":False,"message":"Nenhum scan salvo ainda."}),404
    try: return jsonify(json.loads(SCAN_REPORT.read_text(encoding="utf-8")))
    except Exception as e: return jsonify({"ok":False,"message":str(e)}),500

@app.get("/api/scan/search")
def api_scan_search():
    q=str(request.args.get("q") or "").strip().lower(); client=str(request.args.get("client") or "").strip().lower(); project=str(request.args.get("project") or "").strip().lower(); typ=str(request.args.get("type") or "").strip().lower(); limit=max(1,min(500,int(request.args.get("limit",100))))
    if not SCAN_JSONL.exists(): return jsonify({"ok":False,"message":"Execute um scan primeiro.","results":[]}),404
    out=[]
    try:
        with SCAN_JSONL.open("r",encoding="utf-8",errors="ignore") as f:
            for line in f:
                try:r=json.loads(line)
                except Exception:continue
                if q and q not in (r.get("nome","")+" "+r.get("caminho","")).lower():continue
                if client and client not in " ".join(r.get("clientes",[])).lower():continue
                if project and project not in " ".join(r.get("projetos",[])).lower():continue
                if typ and typ!=str(r.get("tipo","")).lower():continue
                out.append(r)
                if len(out)>=limit:break
    except Exception as e:return jsonify({"ok":False,"message":str(e),"results":[]}),500
    return jsonify({"ok":True,"total":len(out),"results":out})

HTML=r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AURION DYNAMIC</title><style>
:root{--bg:#080c11;--side:#0d141d;--p:#111a25;--p2:#172231;--line:#253446;--txt:#eef5ff;--muted:#8ea0b5;--cyan:#55c8ff;--ok:#4cda86;--warn:#ffd166;--bad:#ff6277}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px Segoe UI,Arial,sans-serif;overflow:hidden}.app{display:flex;height:100vh}.side{width:245px;flex:none;background:var(--side);border-right:1px solid var(--line);padding:18px 12px;overflow:auto}.brand{font-size:22px;font-weight:800;padding:6px 10px}.brand small{display:block;font-size:10px;color:var(--muted);letter-spacing:2px;margin-top:4px}.nav{margin-top:18px}.nav button{width:100%;text-align:left;margin:4px 0;padding:11px 12px;background:transparent;border:1px solid transparent;color:var(--muted);border-radius:9px;cursor:pointer;font-weight:600}.nav button:hover,.nav button.active{background:var(--p2);border-color:var(--line);color:var(--txt)}.side-status{margin-top:18px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#0a1119}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--bad);margin-right:7px}.dot.ok{background:var(--ok)}.main{flex:1;min-width:0;display:flex;flex-direction:column}.top{height:64px;flex:none;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 22px;background:#0b1118}.title{font-size:17px;font-weight:700}.topright{color:var(--muted)}.content{flex:1;overflow:auto;padding:20px}.tab{display:none;max-width:1500px;margin:auto}.tab.active{display:block}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}.card{background:var(--p);border:1px solid var(--line);border-radius:13px;padding:15px;margin-bottom:14px}.card h3{margin:0 0 11px;font-size:13px;color:var(--muted);letter-spacing:.4px}.big{font-size:21px;font-weight:800}.hero{padding:18px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(135deg,#101a26,#0c121a);margin-bottom:14px}.hero h2{margin:0 0 6px}.hero p{margin:0;color:var(--muted)}button.action{background:var(--p2);border:1px solid var(--line);color:var(--txt);padding:10px 12px;border-radius:9px;cursor:pointer;font-weight:600;margin:3px}button.action:hover{border-color:var(--cyan)}button.primary{border-color:var(--cyan);background:#102b3b}.actions{display:flex;flex-wrap:wrap;gap:4px}.bar{height:10px;background:#202b38;border-radius:99px;overflow:hidden}.fill{height:100%;width:0;background:var(--cyan);transition:.25s}.row{display:flex;gap:9px;align-items:center}.row>*{flex:1}input,select,textarea{width:100%;background:#080e15;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:10px;outline:none}textarea{min-height:280px;font:12px Consolas,monospace}.chatlog{height:440px;min-height:180px;max-height:none;overflow:auto;background:#080d13;border:1px solid var(--line);border-radius:10px;padding:13px;margin-bottom:10px;resize:vertical}.msg{padding:9px 11px;border-radius:9px;margin:7px 0;white-space:pre-wrap;word-break:break-word;max-width:92%}.user{background:#13283a;margin-left:auto}.agent{background:#151d28}.sys{background:#241d12;color:var(--warn)}#chat.chat-window{position:fixed;z-index:80;right:22px;bottom:18px;width:min(920px,calc(100vw - 290px));height:min(760px,calc(100vh - 100px));min-width:360px;min-height:300px;max-width:calc(100vw - 24px);max-height:calc(100vh - 82px);overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:0 20px 70px rgba(0,0,0,.55);resize:both}.chat-window .chat-head{cursor:move;user-select:none}.chat-window.chat-minimized{height:58px;min-height:58px;width:360px;min-width:280px;overflow:hidden;padding-bottom:8px}.chat-window.chat-minimized .chat-body{display:none}.chat-min-btn{display:none}@media(max-width:800px){.side{width:70px}.side .nav button{font-size:0}.content{padding:10px}.grid,.grid2{grid-template-columns:1fr}.top{padding:0 10px}.topright{display:none}#chat.chat-window{left:8px;right:8px;bottom:8px;width:auto;height:calc(100vh - 80px);min-width:0;max-width:none}.chat-window.chat-minimized{width:calc(100vw - 16px);height:58px;min-height:58px}}pre{background:#080d13;border:1px solid var(--line);border-radius:10px;padding:12px;max-height:420px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:12px Consolas,monospace}table{width:100%;border-collapse:collapse;font-size:12px}td,th{text-align:left;padding:8px;border-bottom:1px solid var(--line)}label{display:block;color:var(--muted);font-size:12px;margin:9px 0 5px}.progressbox{margin-top:18px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#09111a}.result{min-height:280px;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted)}.pill{display:inline-block;padding:3px 7px;border-radius:99px;border:1px solid var(--line);color:var(--muted);font-size:11px}.model-list{max-height:420px;overflow:auto}.model{display:flex;justify-content:space-between;align-items:center;padding:9px;border-bottom:1px solid var(--line)}.model span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}@media(max-width:950px){.side{width:195px}.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.side{width:64px;padding:10px 5px}.brand{font-size:0}.brand:before{content:'⚡';font-size:24px}.nav button{font-size:0;text-align:center}.nav button:first-letter{font-size:18px}.grid,.grid2{grid-template-columns:1fr}.topright{display:none}}
#chatFab{box-shadow:0 10px 35px rgba(0,0,0,.35)} .notice{color:var(--muted);font-size:12px;margin-top:8px;padding:8px;border:1px solid var(--line);border-radius:8px;background:#09111a}
</style></head><body><div class="app"><aside class="side"><div class="brand">⚡ AURION<small>DYNAMIC LOCAL CORE</small></div><div class="nav">
<button class="active" onclick="tab('home',this)">⌂ &nbsp; PAINEL</button><button onclick="tab('chat',this)">◉ &nbsp; AGENTE / CHAT</button><button onclick="tab('models',this)">◆ &nbsp; MODELOS</button><button onclick="tab('scan',this)">▦ &nbsp; SCAN / PROJETOS</button><button onclick="tab('image',this)">▣ &nbsp; GERAR IMAGEM</button><button onclick="tab('video',this)">▶ &nbsp; GERAR VÍDEO</button><button onclick="tab('render',this)">◈ &nbsp; RENDER / CUDA</button><button onclick="tab('repo',this)">⌘ &nbsp; REPOSITÓRIO / GIT</button><button onclick="tab('drivers',this)">⚙ &nbsp; DRIVERS / DEP.</button><button onclick="tab('cmd',this)">▤ &nbsp; CMD</button><button onclick="tab('logs',this)">☷ &nbsp; LOG / ERROS</button><button onclick="tab('repair',this)">🛠 &nbsp; CONSERTO</button><button onclick="tab('config',this)">⚙ &nbsp; CONFIGURAÇÃO</button></div><div class="side-status"><div><span id="dotA" class="dot"></span>Agente <b id="sideAgent">...</b></div><div style="margin-top:8px"><span id="dotC" class="dot"></span>ComfyUI</div><div style="margin-top:8px"><span id="dotG" class="dot"></span>NVIDIA</div></div></aside><main class="main"><header class="top"><div class="title" id="title">PAINEL</div><div class="topright" id="global">Carregando núcleo...</div><div style="display:flex;gap:5px;align-items:center"><button class="action" onclick="tab('repair',this)">CONSERTO</button><button class="action" onclick="tab('config',this)">CONFIG</button><button class="action" onclick="openUrl('openwebui')">WEBUI</button></div></header><div class="content">
<section id="home" class="tab active"><div class="hero"><h2>AURION DYNAMIC</h2><p>Central local: agente + modelos + ComfyUI + render CUDA + Git + ferramentas.</p></div><div class="grid"><div class="card"><h3>AGENTE</h3><div id="hA" class="big">...</div><small>Ollama</small></div><div class="card"><h3>COMFYUI</h3><div id="hC" class="big">...</div><small id="hCP">...</small></div><div class="card"><h3>NVIDIA / CUDA</h3><div id="hG" class="big">...</div><small id="hGN">...</small></div><div class="card"><h3>MODELOS</h3><div id="hM" class="big">...</div><small id="hMS">...</small></div></div><div class="card"><h3>CARREGAMENTO</h3><div id="op">...</div><div class="bar" style="margin-top:9px"><div id="fill" class="fill"></div></div><div id="loadpct" class="muted" style="margin-top:6px">0%</div></div><div class="card"><h3>NÚCLEO / AUTOMAÇÃO</h3><div class="row"><span><span id="autoDot" class="dot"></span><b id="autoText">AGENTE AUTÔNOMO</b></span><span id="autoLast" class="muted"></span></div><div class="bar" style="margin-top:9px"><div id="autoFill" class="fill"></div></div><small>Monitora serviços, GPU e catálogo e registra as ações automáticas.</small></div><div class="card"><h3>AÇÕES RÁPIDAS</h3><div class="actions"><button class="action primary" onclick="post('/api/setup')">CORRIGIR TUDO</button><button class="action" onclick="post('/api/restart-services')">RECARREGAR SERVIÇOS</button><button class="action" onclick="post('/api/start/comfy')">INICIAR COMFYUI</button><button class="action" onclick="post('/api/start/ollama')">INICIAR AGENTE</button><button class="action" onclick="post('/api/start/openwebui')">INICIAR OPEN WEBUI</button><button class="action" onclick="post('/api/cmd')">ABRIR CMD</button><button class="action" onclick="post('/api/scan')">SCAN LOCAL</button><button class="action primary" onclick="post('/api/scan-completo')">SCAN A:–Z:</button></div></div></section>
<section id="chat" class="tab chat-window"><div class="chat-head" id="chatDrag"><div style="display:flex;align-items:center;justify-content:space-between;gap:8px"><h3 style="margin:0">AGENTE AURION — CHAT LOCAL</h3><div class="actions"><button class="action" onclick="toggleChat(event)">MINIMIZAR</button><button class="action" onclick="clearChat(event)">LIMPAR</button></div></div><div class="row" style="margin-top:10px"><select id="agentModel"><option>Carregando...</option></select><button class="action primary" onclick="loadAgent()">CARREGAR AGENTE</button></div><div id="agentStatus" class="notice">Aguardando agente...</div></div><div class="chat-body"><div class="grid2"><div class="card"><div id="chatlog" class="chatlog"><div class="msg sys">AURION: preparando o agente local...</div></div><div class="row"><input id="chatInput" placeholder="Fale com o agente AURION..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChat()}"><button class="action primary" onclick="sendChat()">ENVIAR</button></div></div><div class="card"><h3>🧠 CÉREBRO / APRENDIZADO</h3><textarea id="learnNote" style="min-height:90px" placeholder="Regra ou preferência que o AURION deve aprender..."></textarea><button class="action primary" onclick="learnNote()">APRENDER E SALVAR</button><span id="learnStatus" class="muted"></span><h3 style="margin-top:18px">🧠 MEMÓRIA / MENTE</h3><input id="memTitle" placeholder="Nome da memória"><textarea id="memContent" style="min-height:170px" placeholder="Cole regras, contexto, roteiro ou informações para o agente..."></textarea><div class="actions"><button class="action primary" onclick="saveMemory()">💾 SALVAR MEMÓRIA</button><button class="action" onclick="clearMemory()">LIMPAR</button></div><div id="memoryList" class="model-list">Carregando memórias...</div></div></div></div></section><section id="models" class="tab"><div class="grid2"><div class="card"><h3>MODELOS LOCAIS — COMFYUI</h3><div id="modelSummary" class="muted" style="margin-bottom:8px">Escaneando modelos reais...</div><div id="localModels" class="model-list">...</div></div><div class="card"><h3>MODELOS DO AGENTE — OLLAMA</h3><div id="ollamaModels" class="model-list">...</div></div></div><div class="card"><h3>SLOTS REAIS DO COMFYUI</h3><div class="grid2"><div><label>Checkpoints</label><div id="slotCheckpoints" class="model-list"></div></div><div><label>LoRAs</label><div id="slotLoras" class="model-list"></div></div><div><label>VAE</label><div id="slotVae" class="model-list"></div></div><div><label>ControlNet</label><div id="slotControlnet" class="model-list"></div></div></div></div><div class="card"><h3>AÇÕES</h3><div class="actions"><button class="action primary" onclick="post('/api/configure-models')">LIGAR MODELOS AO COMFYUI</button><button class="action" onclick="post('/api/download-comfy')">BAIXAR COMFYUI</button><button class="action" onclick="post('/api/dependencies')">ATUALIZAR DEPENDÊNCIAS</button></div></div></section>
<section id="scan" class="tab"><div class="hero"><h2>SCAN / PROJETOS / CLIENTES</h2><p>Indexa sem mover ou apagar arquivos. Classifica por cliente, projeto, modelo, código, imagem, vídeo, áudio e documentos.</p><div class="actions"><button class="action primary" onclick="post('/api/scan')">SCAN LOCAL</button><button class="action" onclick="post('/api/scan-completo')">SCAN A:–Z:</button><button class="action" onclick="loadScan()">ATUALIZAR RELATÓRIO</button></div></div><div class="grid"><div class="card"><h3>ARQUIVOS</h3><div id="scFiles" class="big">0</div></div><div class="card"><h3>CLIENTES</h3><div id="scClients" class="big">0</div></div><div class="card"><h3>PROJETOS</h3><div id="scProjects" class="big">0</div></div><div class="card"><h3>TAMANHO</h3><div id="scSize" class="big">0 B</div></div></div><div class="grid2"><div class="card"><h3>CLIENTES DETECTADOS</h3><pre id="scClientList">Nenhum scan.</pre></div><div class="card"><h3>PROJETOS DETECTADOS</h3><pre id="scProjectList">Nenhum scan.</pre></div></div><div class="card"><h3>TIPOS DE ARQUIVO</h3><pre id="scTypes">Nenhum scan.</pre></div><div class="card"><h3>ARQUIVOS DE MAIOR TAMANHO</h3><pre id="scTop">Nenhum scan.</pre></div></section>
<section id="image" class="tab"><div class="hero"><h2>GERAR IMAGEM</h2><p>Geração direta pelo ComfyUI. O AURION mostra fila, progresso e resultado.</p></div><div class="grid2"><div class="card"><h3>PARÂMETROS</h3><label>Modelo / Checkpoint</label><select id="imgCheckpoint"><option>Carregando...</option></select><label>LoRA (opcional)</label><select id="imgLora"><option value="">Nenhuma</option></select><label>VAE (catálogo)</label><select id="imgVae"><option value="">Automático do checkpoint</option></select><label>ControlNet (catálogo)</label><select id="imgControlnet"><option value="">Nenhum</option></select><label>Imagem de referência (ControlNet)</label><input id="imgControlImage" type="file" accept="image/png,image/jpeg,image/webp,image/bmp"><label>Prompt</label><textarea id="imgPrompt" placeholder="Descreva a imagem..."></textarea><label>Negative Prompt</label><textarea id="imgNegative" style="min-height:90px">low quality, blurry, distorted, duplicate, watermark</textarea></div><div class="card"><h3>GERAÇÃO</h3><div class="grid2"><div><label>Largura</label><input id="imgW" type="number" value="1024"></div><div><label>Altura</label><input id="imgH" type="number" value="1024"></div><div><label>Steps</label><input id="imgSteps" type="number" value="28"></div><div><label>CFG</label><input id="imgCfg" value="7"></div></div><label>Seed (-1 = aleatória)</label><input id="imgSeed" type="number" value="-1"><label><input id="imgAutoAgent" type="checkbox" checked style="width:auto;margin-right:6px"> AGENTE DECIDE O MELHOR MODELO/PARÂMETROS</label><div id="agentPlan" class="muted"></div><div class="actions"><button class="action primary" onclick="generateImage()">⚡ GERAR IMAGEM</button><button class="action" onclick="cancelImage()">CANCELAR</button><button class="action" onclick="openUrl('comfy')">ABRIR COMFYUI</button></div><div class="progressbox"><div class="bar"><div id="imgFill" class="fill"></div></div><div id="imgProgressText">AGUARDANDO — 0%</div><small id="imgProgressDetail">Nenhuma geração ativa.</small></div></div></div><div class="card"><h3>RESULTADO</h3><div id="imgResult" class="result">A imagem aparecerá aqui quando o ComfyUI terminar.</div></div></section><section id="video" class="tab"><div class="hero"><h2>GERAÇÃO DE VÍDEO</h2><p>Área dedicada aos pipelines de vídeo no ComfyUI, usando a NVIDIA/CUDA para inferência e render.</p></div><div class="card"><h3>WORKFLOW DE VÍDEO — COMFYUI</h3><textarea id="vw" placeholder='Cole o workflow/API JSON do seu pipeline de vídeo (Wan, HunyuanVideo, AnimateDiff etc.).'></textarea><div class="actions"><button class="action primary" onclick="queue('vw')">ENVIAR PARA RENDER</button><button class="action" onclick="openUrl('comfy')">ABRIR COMFYUI</button></div></div><div class="card"><h3>GPU</h3><pre id="vg">...</pre></div></section>
<section id="render" class="tab"><div class="grid2"><div class="card"><h3>NVIDIA / CUDA</h3><pre id="gpu">...</pre></div><div class="card"><h3>COMFYUI / RENDER</h3><pre id="cs">...</pre></div></div><div class="card"><h3>AÇÕES DE RENDER</h3><div class="actions"><button class="action primary" onclick="refresh()">ATUALIZAR GPU</button><button class="action" onclick="openUrl('comfy')">ABRIR COMFYUI</button></div></div></section>
<section id="repo" class="tab"><div class="card"><h3>REPOSITÓRIOS / GIT</h3><div id="repos">...</div></div><div class="card"><h3>AÇÕES</h3><div class="actions"><button class="action primary" onclick="post('/api/git/comfy-update')">ATUALIZAR COMFYUI — GIT PULL</button><button class="action" onclick="post('/api/git/update')">ATUALIZAR PROJETO</button><button class="action" onclick="post('/api/download-comfy')">BAIXAR / INSTALAR COMFYUI</button></div></div></section>
<section id="drivers" class="tab"><div class="grid2"><div class="card"><h3>DRIVER NVIDIA</h3><pre id="driver">...</pre></div><div class="card"><h3>DEPENDÊNCIAS</h3><pre id="deps">...</pre></div></div><div class="card"><h3>MANUTENÇÃO</h3><div class="actions"><button class="action primary" onclick="post('/api/dependencies')">ATUALIZAR DEPENDÊNCIAS</button><button class="action" onclick="openCmd()">CMD</button><button class="action" onclick="refresh()">DIAGNÓSTICO</button></div></div></section>
<section id="cmd" class="tab"><div class="hero"><h2>CMD / TERMINAL LOCAL</h2><p>Abre o terminal diretamente na pasta base do AURION.</p></div><div class="card"><div class="actions"><button class="action primary" onclick="openCmd()">ABRIR CMD</button><button class="action" onclick="openUrl('panel')">PAINEL</button><button class="action" onclick="openUrl('comfy')">COMFYUI</button><button class="action" onclick="openUrl('openwebui')">OPEN WEBUI</button></div></div></section>
<section id="repair" class="tab"><div class="hero"><h2>CONSERTO / AUTO-DIAGNÓSTICO</h2><p>Verificação real de serviços, GPU, caminhos de modelos, dependências e agente.</p><div class="actions"><button class="action primary" onclick="post('/api/setup')">CORRIGIR TUDO</button><button class="action" onclick="post('/api/configure-models')">REFAZER SLOTS</button><button class="action" onclick="post('/api/dependencies')">DEPENDÊNCIAS</button><button class="action" onclick="post('/api/restart-services')">RECARREGAR NÚCLEO</button></div></div><div class="grid"><div class="card"><h3>OLLAMA</h3><div id="fixO" class="big">...</div></div><div class="card"><h3>COMFYUI</h3><div id="fixC" class="big">...</div></div><div class="card"><h3>NVIDIA</h3><div id="fixN" class="big">...</div></div><div class="card"><h3>OPEN WEBUI</h3><div id="fixW" class="big">...</div></div></div><div class="card"><h3>AUTOMAÇÃO DO CÉREBRO</h3><div class="actions"><button class="action primary" onclick="setAutomation(true)">ATIVAR</button><button class="action" onclick="setAutomation(false)">PAUSAR</button></div><pre id="autoLog">...</pre></div></section><section id="config" class="tab"><div class="hero"><h2>CONFIGURAÇÃO</h2><p>Operador, agente, integrações e preferências.</p></div><div class="grid2"><div class="card"><h3>OPERADOR / AGENTE</h3><label>Operador</label><input id="operator"><label>Modelo do agente</label><select id="agentModelCfg"></select><label>URL ComfyUI</label><input id="comfyurl" value="http://127.0.0.1:8188"><label>URL Ollama</label><input id="ollamaurl" value="http://127.0.0.1:11434"><button class="action primary" onclick="saveConfig()">SALVAR</button></div><div class="card"><h3>INTEGRAÇÕES</h3><div class="actions"><button class="action" onclick="openExternal('https://github.com/')">GITHUB / LOGIN</button><button class="action" onclick="openExternal('https://huggingface.co/login')">HUGGING FACE / LOGIN</button><button class="action" onclick="openExternal('https://accounts.google.com/')">GOOGLE / LOGIN</button><button class="action" onclick="openUrl('openwebui')">OPEN WEBUI</button></div><label>Hugging Face — repositórios</label><textarea id="hfrepos" style="min-height:130px"></textarea><button class="action" onclick="saveHF()">SALVAR HF</button></div></div></section><section id="logs" class="tab"><div class="grid2"><div class="card"><h3>LOG DO AURION</h3><pre id="logs">...</pre></div><div class="card"><h3>LOG DE ERROS</h3><pre id="errors">...</pre></div></div><div class="card"><h3>DIAGNÓSTICO JSON</h3><pre id="diag">...</pre></div></section>
</div></main></div><script>
const titles={home:'PAINEL',chat:'AGENTE / CHAT',models:'MODELOS',scan:'SCAN / PROJETOS',image:'GERAR IMAGEM',video:'GERAR VÍDEO',render:'RENDER / CUDA',repo:'REPOSITÓRIO / GIT',drivers:'DRIVERS / DEPENDÊNCIAS',cmd:'CMD',logs:'LOG / ERROS',repair:'CONSERTO',config:'CONFIGURAÇÃO'};
function tab(id,b){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));if(b)b.classList.add('active');document.getElementById('title').textContent=titles[id]||id;if(id==='chat'){document.getElementById('chatFab')?.style.setProperty('display','none')}else{document.getElementById('chatFab')?.style.setProperty('display','block')}}
function toggleFloatingChat(){let c=document.getElementById('chat');if(!c)return;c.classList.toggle('active');c.classList.remove('chat-minimized');if(c.classList.contains('active'))loadModels()}
function txt(id,v){let e=document.getElementById(id);if(e)e.textContent=v??''}function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
async function post(u){try{let r=await fetch(u,{method:'POST'}),d=await r.json();txt('global',d.message||d.reply||(d.ok?'OK':'Falhou'))}catch(e){txt('global','Erro: '+e)}setTimeout(refresh,700)}function openCmd(){post('/api/cmd')}function openUrl(n){fetch('/api/open/'+n,{method:'POST'})}
async function refresh(){try{let d=await (await fetch('/api/status',{cache:'no-store'})).json(),x=d.diagnostics,s=d.state,h=x.health||{};let a=x.ollama.model||'não carregado';txt('hA',a);txt('sideAgent',a);txt('hC',h.comfy?'ONLINE':(x.comfy.found?'ENCONTRADO':'NÃO ENCONTRADO'));txt('hCP',x.comfy.path||'nenhum caminho');txt('hG',h.nvidia?'ONLINE':'NÃO DETECTADA');txt('hGN',x.nvidia.gpus?.map(g=>g.name).join(' | ')||'nvidia-smi');txt('hM',x.models_inventory.total+' arquivos');txt('hMS',x.models_inventory.size);txt('op',(s.busy?s.operation+' — ':'')+s.message);document.getElementById('fill').style.width=s.progress+'%';txt('loadpct',s.progress+'%');txt('global',s.message);document.getElementById('dotA').className='dot '+(h.ollama?'ok':'');document.getElementById('dotC').className='dot '+(h.comfy?'ok':'');document.getElementById('dotG').className='dot '+(h.nvidia?'ok':'');txt('fixO',h.ollama?'ONLINE':'OFFLINE');txt('fixC',h.comfy?'ONLINE':'OFFLINE');txt('fixN',h.nvidia?'ONLINE':'OFFLINE');txt('fixW',h.openwebui?'ONLINE':'OFFLINE');let au=s.automation||{},on=au.enabled!==false;document.getElementById('autoDot').className='dot '+(on?'ok':'');txt('autoText',on?'AGENTE AUTÔNOMO ON':'AGENTE AUTÔNOMO PAUSADO');txt('autoLast',au.last_check||'');document.getElementById('autoFill').style.width=(on?100:0)+'%';txt('autoLog',(au.actions||[]).slice(-30).join('\n')||'Sem ações automáticas.');txt('gpu',JSON.stringify(x.nvidia,null,2));txt('vg',JSON.stringify(x.nvidia,null,2));txt('driver',JSON.stringify(x.nvidia,null,2));txt('deps',JSON.stringify(x.tools,null,2));txt('diag',JSON.stringify(x,null,2));txt('logs',(s.logs||[]).join('\n')||'Sem logs.');txt('errors',(s.errors||[]).join('\n')||'Sem erros.');try{let z=await (await fetch('/api/comfy/stats')).json();txt('cs',JSON.stringify(z,null,2))}catch(e){txt('cs','ComfyUI offline.')}loadModels();loadRepos();loadScan()}catch(e){txt('global','Aguardando serviços...')}}
async function loadModels(){try{let d=await (await fetch('/api/models',{cache:'no-store'})).json(),lm=d.local.files||[],om=d.ollama||[];document.getElementById('localModels').innerHTML=lm.length?lm.map(m=>`<div class="model"><span>${esc(m.name)}<br><small>${esc(m.category)} · ${esc(m.path)} · ${esc(m.size)}</small></span><span class="pill">${esc(m.architecture||m.ext)}</span></div>`).join(''):'Nenhum modelo local encontrado.';txt('modelSummary',(d.local.total||0)+' arquivos de modelo detectados · '+(d.local.size||'0 B')+' · raízes '+((d.local.roots||[]).length));document.getElementById('ollamaModels').innerHTML=om.length?om.map(m=>`<div class="model"><span>${esc(m.name)}<br><small>${esc(m.size||'')}</small></span><button class="action" onclick="setModel(${JSON.stringify(m.name)})">CARREGAR</button></div>`).join(''):'Nenhum modelo Ollama.';let s=document.getElementById('agentModel');s.innerHTML=om.length?om.map(m=>`<option value="${esc(m.name)}">${esc(m.name)}</option>`).join(''):'<option value="">Nenhum modelo</option>';if(d.agent_model)s.value=d.agent_model;let cfg=document.getElementById('agentModelCfg');if(cfg){cfg.innerHTML=om.map(m=>`<option value="${esc(m.name)}">${esc(m.name)}</option>`).join('');if(d.agent_model)cfg.value=d.agent_model}renderSlots(lm);loadImageOptions();loadMemory()}catch(e){txt('agentStatus','Falha ao carregar modelos: '+e)}}
function renderSlots(files){let cats={checkpoints:'slotCheckpoints',loras:'slotLoras',vae:'slotVae',controlnet:'slotControlnet'};for(let c in cats){let e=document.getElementById(cats[c]);if(!e)continue;let arr=files.filter(x=>x.category===c);e.innerHTML=arr.length?arr.slice(0,500).map(x=>`<div class="model"><span>${esc(x.name)}<br><small>${esc(x.path)} · ${esc(x.size)}</small></span><span class="pill">${esc(x.architecture||c)}</span></div>`).join(''):'Nenhum encontrado';}}
async function setModel(m){let r=await fetch('/api/agent/model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:m})});let d=await r.json();txt('agentStatus',d.message||'Modelo selecionado.');refresh()}function selectAgent(){setModel(document.getElementById('agentModel').value)}async function loadAgent(){let m=document.getElementById('agentModel').value;txt('agentStatus','Carregando e aquecendo '+m+'...');try{let r=await fetch('/api/agent/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:m})}),d=await r.json();txt('agentStatus',d.message||d.model||'Agente carregado.');await loadModels();}catch(e){txt('agentStatus','Erro: '+e)}}

async function learnNote(){let v=document.getElementById('learnNote').value.trim();if(!v)return;let r=await fetch('/api/agent/learn',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:v})});let d=await r.json();txt('learnStatus',d.message||'');if(d.ok)document.getElementById('learnNote').value='';refresh()}
async function setAutomation(v){let r=await fetch('/api/automation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:v})});let d=await r.json();txt('global',d.message||'');refresh()}
function openExternal(u){window.open(u,'_blank','noopener')}
async function saveConfig(){let body={operator:document.getElementById('operator')?.value||'',comfy_url:document.getElementById('comfyurl')?.value||'',ollama_url:document.getElementById('ollamaurl')?.value||'',huggingface_repos:(document.getElementById('hfrepos')?.value||'').split(/[,;\n]+/).map(x=>x.trim()).filter(Boolean),agent_model:document.getElementById('agentModelCfg')?.value||''};let r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let d=await r.json();txt('global',d.message||'Configuração salva.')}
async function saveHF(){await saveConfig()}
async function sendChat(){let i=document.getElementById('chatInput'),m=i.value.trim();if(!m)return;let b=document.getElementById('chatlog');b.innerHTML+=`<div class="msg user"><b>VOCÊ</b><br>${esc(m)}</div>`;i.value='';b.innerHTML+=`<div class="msg sys" id="chatThinking">AURION: processando...</div>`;b.scrollTop=b.scrollHeight;try{let model=document.getElementById('agentModel').value,r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,model})}),d=await r.json();document.getElementById('chatThinking')?.remove();b.innerHTML+=`<div class="msg agent"><b>AURION · ${esc(d.model||model||'agente')}</b><br>${esc(d.reply||'Sem resposta.')}</div>`}catch(e){document.getElementById('chatThinking')?.remove();b.innerHTML+=`<div class="msg sys">ERRO: ${esc(e)}</div>`}b.scrollTop=b.scrollHeight}
async function loadChatHistory(){try{let d=await (await fetch('/api/chat/history',{cache:'no-store'})).json(),b=document.getElementById('chatlog');if(!b||!d.messages?.length)return;b.innerHTML=d.messages.map(x=>`<div class="msg ${x.role==='user'?'user':'agent'}"><b>${x.role==='user'?'VOCÊ':'AURION · '+esc(x.model||'agente')}</b><br>${esc(x.content||'')}</div>`).join('');b.scrollTop=b.scrollHeight}catch(e){}}
async function clearChat(ev){ev?.stopPropagation();await fetch('/api/chat/clear',{method:'POST'});document.getElementById('chatlog').innerHTML='<div class="msg sys">Histórico limpo.</div>'}
function toggleChat(ev){ev?.stopPropagation();document.getElementById('chat').classList.toggle('chat-minimized')}
(function setupChatDrag(){let c=document.getElementById('chat'),h=document.getElementById('chatDrag');if(!c||!h)return;let drag=false,sx=0,sy=0,ox=0,oy=0;h.addEventListener('pointerdown',e=>{if(e.target.closest('button,input,select,textarea'))return;drag=true;h.setPointerCapture(e.pointerId);sx=e.clientX;sy=e.clientY;let r=c.getBoundingClientRect();ox=r.left;oy=r.top;c.style.right='auto';c.style.bottom='auto';c.style.left=ox+'px';c.style.top=oy+'px'});h.addEventListener('pointermove',e=>{if(!drag)return;let nx=Math.max(8,Math.min(window.innerWidth-c.offsetWidth-8,ox+e.clientX-sx));let ny=Math.max(8,Math.min(window.innerHeight-c.offsetHeight-8,oy+e.clientY-sy));c.style.left=nx+'px';c.style.top=ny+'px'});h.addEventListener('pointerup',()=>drag=false)})();

async function queue(id){let t=document.getElementById(id).value.trim();if(!t){alert('Cole o workflow/API JSON do ComfyUI primeiro.');return}try{let r=await fetch('/api/comfy/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow:t})}),d=await r.json();txt('global',d.ok?'Workflow enviado ao ComfyUI.':'Erro: '+d.message)}catch(e){txt('global','Erro: '+e)}}
async function loadScan(){try{let d=await (await fetch('/api/scan/report',{cache:'no-store'})).json();if(!d.ok){return}txt('scFiles',d.arquivos);txt('scClients',Object.keys(d.clientes||{}).length);txt('scProjects',Object.keys(d.projetos||{}).length);txt('scSize',d.tamanho||'0 B');txt('scClientList',Object.entries(d.clientes||{}).slice(0,200).map(([n,x])=>n+' | '+x.arquivos+' arquivos | '+hsizeJS(x.bytes)+' | '+x.pasta).join('\n')||'Nenhum');txt('scProjectList',Object.entries(d.projetos||{}).slice(0,200).map(([n,x])=>n+' | '+x.arquivos+' arquivos | '+hsizeJS(x.bytes)+' | '+x.pasta).join('\n')||'Nenhum');txt('scTypes',JSON.stringify(d.por_tipo||{},null,2));txt('scTop',(d.arquivos_destaque||[]).slice(0,100).map(x=>x.tamanho+' | '+x.tipo+' | '+x.caminho).join('\n')||'Nenhum')}catch(e){}}function hsizeJS(n){n=Number(n)||0;let u=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(1)+' '+u[i]}
async function loadRepos(){try{let d=await (await fetch('/api/git')).json(),rs=d.repos||[];document.getElementById('repos').innerHTML=rs.length?rs.map(r=>`<div class="card" style="margin:7px 0"><b>${esc(r.path)}</b><br>branch: <span class="pill">${esc(r.branch||'-')}</span> ${r.dirty?'<span class="pill">ALTERADO</span>':'<span class="pill">LIMPO</span>'}<pre>${esc(r.status||r.remote||'')}</pre><button class="action" onclick="gitPull('${esc(r.path)}')">GIT PULL</button></div>`).join(''):'Nenhum repositório Git detectado.'}catch(e){}}
async function gitPull(p){let r=await fetch('/api/git/update?path='+encodeURIComponent(p),{method:'POST'}),d=await r.json();txt('global',d.message||'Git pull iniciado.');setTimeout(refresh,600)}refresh();loadChatHistory();setInterval(refresh,3000);

async function loadMemory(){try{let d=await (await fetch('/api/memory/list',{cache:'no-store'})).json();let e=document.getElementById('memoryList');e.innerHTML=(d.files||[]).length?(d.files.map(x=>`<div class="model" onclick='openMemory(${JSON.stringify(x.path)})"><span>${esc(x.name)}<br><small>${esc(x.category)} · ${esc(x.modified)}</small></span></div>`).join('')):'Nenhuma memória salva.'}catch(e){}}
async function openMemory(path){let r=await fetch('/api/memory/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}),d=await r.json();if(d.ok){document.getElementById('memContent').value=d.content;document.getElementById('memTitle').value=path.split(/[\\/]/).pop().replace(/\.md$/i,'')}}
async function saveMemory(){let title=document.getElementById('memTitle').value,content=document.getElementById('memContent').value;let r=await fetch('/api/memory/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,content})}),d=await r.json();txt('agentStatus',d.message||d.error||'');loadMemory()}
function clearMemory(){document.getElementById('memTitle').value='';document.getElementById('memContent').value=''}
async function loadImageOptions(){try{let d=await (await fetch('/api/image/options',{cache:'no-store'})).json(),s=document.getElementById('imgCheckpoint');if(!s)return;s.innerHTML=(d.checkpoints||[]).map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')||'<option value="">Nenhum checkpoint</option>';for(let [id,key,empty] of [['imgLora','loras','Nenhuma'],['imgVae','vae','Automático do checkpoint'],['imgControlnet','controlnet','Nenhum']]){let e=document.getElementById(id);if(e)e.innerHTML=`<option value="">${empty}</option>`+(d.slots?.[key]||[]).map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')}}catch(e){}}
async function generateImage(){
 let p=document.getElementById('imgPrompt').value.trim();if(!p){txt('imgProgressText','DIGITE UM PROMPT');return}
 let auto=document.getElementById('imgAutoAgent').checked;txt('imgProgressText',auto?'PLANEJANDO — 0%':'ENVIANDO — 0%');txt('imgProgressDetail',auto?'Agente escolhendo modelo e parâmetros...':'Enviando ao ComfyUI...');document.getElementById('imgFill').style.width='2%';
 let control_image='';
 try{
  let f=document.getElementById('imgControlImage')?.files?.[0];
  if(f){let fd=new FormData();fd.append('file',f);let ur=await (await fetch('/api/image/upload',{method:'POST',body:fd})).json();if(!ur.ok){txt('imgProgressText','ERRO');txt('imgProgressDetail',ur.message||'Falha no upload');return}control_image=ur.comfy_name}
  let body={prompt:p,negative:document.getElementById('imgNegative').value,checkpoint:document.getElementById('imgCheckpoint').value,width:document.getElementById('imgW').value,height:document.getElementById('imgH').value,steps:document.getElementById('imgSteps').value,cfg:document.getElementById('imgCfg').value,seed:document.getElementById('imgSeed').value,auto_agent:auto,lora:document.getElementById('imgLora')?.value||'',vae:document.getElementById('imgVae')?.value||'',controlnet:document.getElementById('imgControlnet')?.value||'',control_image};
  if(auto){let ad=await (await fetch('/api/image/advice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:p,negative:body.negative,checkpoint:body.checkpoint})})).json();if(ad.ok){let pl=ad.plan||{};body.checkpoint=pl.checkpoint||body.checkpoint;body.width=pl.width||body.width;body.height=pl.height||body.height;body.steps=pl.steps||body.steps;body.cfg=pl.cfg||body.cfg;txt('agentPlan','AGENTE: '+(body.checkpoint||'—')+' · '+body.width+'x'+body.height+' · steps '+body.steps+' · CFG '+body.cfg)}}
  document.getElementById('imgFill').style.width='5%';txt('imgProgressText','ENVIANDO — 5%');let r=await fetch('/api/image/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json();if(!d.ok){txt('imgProgressText','ERRO');txt('imgProgressDetail',(d.message||'Falha')+(d.detail?' · '+d.detail:''));return}pollImage(d.prompt_id)
 }catch(e){txt('imgProgressText','ERRO');txt('imgProgressDetail',String(e))}
}
async function cancelImage(){let pid=window.AURION_IMAGE_PID;if(!pid){txt('imgProgressDetail','Nenhuma geração ativa.');return}try{let d=await (await fetch('/api/image/cancel/'+encodeURIComponent(pid),{method:'POST'})).json();txt('imgProgressText',d.ok?'CANCELADO':'ERRO');txt('imgProgressDetail',d.message||'')}catch(e){txt('imgProgressText','ERRO');txt('imgProgressDetail',String(e))}}
async function pollImage(pid){window.AURION_IMAGE_PID=pid;for(let i=0;i<2400;i++){try{let d=await (await fetch('/api/image/progress/'+encodeURIComponent(pid),{cache:'no-store'})).json();let pct=Number(d.progress||0);document.getElementById('imgFill').style.width=pct+'%';txt('imgProgressText',(d.status||'PROCESSANDO').toUpperCase()+' — '+pct+'%');txt('imgProgressDetail',(d.elapsed?d.elapsed+'s · ':'')+'prompt_id: '+pid+(d.message?' · '+d.message:''));if(d.status==='erro'||d.ok===false)return;if(d.images&&d.images.length){document.getElementById('imgFill').style.width='100%';txt('imgProgressText','CONCLUÍDO — 100%');document.getElementById('imgResult').innerHTML=d.images.map(x=>`<img src="${COMFY_VIEW(x)}" style="max-width:100%;border-radius:10px;margin:6px">`).join('');window.AURION_IMAGE_PID=null;return}}catch(e){txt('imgProgressDetail','Falha consultando progresso: '+e)}await new Promise(r=>setTimeout(r,1500))}}
function COMFY_VIEW(x){let q=new URLSearchParams({filename:x.filename,subfolder:x.subfolder||'',type:x.type||'output'});return 'http://127.0.0.1:8188/view?'+q.toString()}
</script><button id="chatFab" class="action primary" onclick="toggleFloatingChat()" style="position:fixed;right:22px;bottom:20px;z-index:120;border-radius:999px;padding:12px 16px">◉ AGENTE</button></body></html>'''

if __name__=="__main__":
    ensure_dirs();print("="*72);print(" AURION — PAINEL LOCAL");print("="*72);print(f" Base    : {PROJECT}");print(f" Modelos : {MODELS}");print(f" Painel  : http://{HOST}:{PORT}");print("="*72)
    d=diagnose();print(f"Python  : {d['python']}");print(f"ComfyUI : {d['comfy']['found']} | {d['comfy'].get('path')}");print(f"Ollama  : {d['ollama']['running']} | agente={d['ollama'].get('model')}");print(f"WebUI   : {d['openwebui']['running']}");print(f"NVIDIA  : {len(d['nvidia'].get('gpus',[]))} GPU(s)");print(f"Modelos : {d['models_inventory']['total']} | {d['models_inventory']['size']}");print("="*72)
    threading.Thread(target=startup,daemon=True).start();threading.Thread(target=autonomous_supervisor,daemon=True).start();threading.Timer(1.2,lambda:webbrowser.open(f"http://{HOST}:{PORT}")).start();app.run(host=HOST,port=PORT,debug=False,threaded=True,use_reloader=False)
