"""Serveur web : comptes, conversations par utilisateur, fichiers.

Local :  python web.py  puis http://localhost:8002
En ligne : l'hébergeur fournit la variable PORT (voir README / render.yaml)."""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import db
from agent import Chat, available_providers

ONLINE = bool(os.getenv("PORT"))  # l'hébergeur définit PORT
PORT = int(os.getenv("PORT", "8002"))
HOST = "0.0.0.0" if ONLINE else "127.0.0.1"
SIGNUP_CODE = os.getenv("SIGNUP_CODE", "").strip()  # si défini : requis pour créer un compte
ALLOW_SIGNUP = os.getenv("ALLOW_SIGNUP", "1") != "0"
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "50"))  # messages / jour / utilisateur (0 = illimité)
MAX_BODY = (4 if os.getenv("VERCEL") else 12) * 1024 * 1024  # Vercel : 4,5 Mo max
ID_RE = re.compile(r"^[0-9a-f]{12}$")
USER_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")

PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#050508">
<title>Mon IA</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;display:flex;height:100vh;height:100dvh}
aside{width:260px;flex:none;background:#0b0b0b;border-right:1px solid #222;display:flex;flex-direction:column;padding:10px;gap:10px;box-sizing:border-box}
#list{flex:1;overflow-y:auto}
.item{padding:9px 10px;border-radius:8px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:6px;font-size:14px;margin-bottom:2px}
.item:hover{background:#1c1c1c}.item.on{background:#242b3d}
.item span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.act{display:flex;flex:none;gap:2px}
.item b,.item i{opacity:0;cursor:pointer;padding:0 5px;font-style:normal;font-weight:400}.item b{color:#e66}.item i{color:#9a92ff}
.item:hover b,.item:hover i{opacity:1}
@media(hover:none){.item b,.item i{opacity:.75}}
.tools{margin-top:10px;display:flex;gap:8px}.tools button{background:#2c2c2c;padding:5px 11px;font-size:12px;color:#bbb;border:1px solid #333}.tools button:hover{color:#fff}
@keyframes pulse{50%{opacity:.35}}.status{color:#9a92ff;animation:pulse 1.4s infinite}
#top,.scrim{display:none}
#top .mark svg{width:34px;height:34px}#top .mark{width:34px;height:34px}#top .word{font-size:24px}
.empty{color:#777;font-size:13px;padding:8px}
.me{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#aaa;border-top:1px solid #222;padding-top:10px}
.me button{padding:6px 10px;font-size:12px;background:#333}
main{flex:1;display:flex;flex-direction:column;min-width:0;height:100vh;height:100dvh}
#log{flex:1;overflow-y:auto;padding:16px;max-width:800px;width:100%;margin:0 auto;box-sizing:border-box}
.m{padding:10px 14px;margin:8px 0;border-radius:10px;white-space:pre-wrap;line-height:1.5}
.u{background:#2a4d8f;margin-left:20%}.a{background:#222;margin-right:10%}
form{display:flex;gap:8px;padding:12px;max-width:800px;width:100%;margin:0 auto;box-sizing:border-box}
input{flex:1;padding:12px;border-radius:8px;border:1px solid #444;background:#1a1a1a;color:#eee;font-size:16px}
button{padding:12px 18px;border-radius:8px;border:0;background:#2a4d8f;color:#fff;cursor:pointer}
.a{white-space:normal;line-height:1.7;font-size:15.5px;overflow-wrap:anywhere}
.a>*:first-child{margin-top:0}.a>*:last-child{margin-bottom:0}
.a p{margin:0 0 14px}
.a h1,.a h2,.a h3,.a h4{margin:22px 0 10px;line-height:1.3}
.a h1{font-size:1.4em}.a h2{font-size:1.25em;border-bottom:1px solid #333;padding-bottom:6px}.a h3{font-size:1.1em}
.a ul,.a ol{margin:0 0 14px;padding-left:26px}.a li{margin:6px 0}
.a hr{border:0;border-top:1px solid #333;margin:18px 0}
.a strong{color:#fff}
.a blockquote{margin:0 0 14px;padding:4px 14px;border-left:3px solid #2a4d8f;color:#bbb}
.a code{background:#333;padding:2px 6px;border-radius:5px;font-size:.9em}
.a pre{background:#0b0b0b;border:1px solid #333;border-radius:8px;padding:12px 14px;overflow-x:auto;margin:0 0 14px}
.a pre code{background:none;padding:0;line-height:1.5}
.a table{border-collapse:collapse;width:100%;margin:0 0 14px;display:block;overflow-x:auto}
.a th,.a td{border:1px solid #3a3a3a;padding:8px 12px;text-align:left;vertical-align:top}
.a th{background:#2c2c2c}.a tr:nth-child(even) td{background:#1c1c1c}
.dl{display:inline-block;margin:10px 8px 0 0;padding:8px 14px;border-radius:8px;background:#1f8a4c;color:#fff;text-decoration:none}

.logo{display:flex;align-items:center;gap:12px;text-decoration:none;color:#fff;padding:4px 6px 8px}
.mark{width:46px;height:46px;flex:none;display:block;filter:drop-shadow(0 0 5px rgba(120,108,255,.9)) drop-shadow(0 0 12px rgba(108,99,255,.55));transition:filter .4s}
.mark svg{display:block}
.logo:hover .mark{filter:drop-shadow(0 0 7px rgba(140,128,255,1)) drop-shadow(0 0 18px rgba(108,99,255,.8))}
.word{font-family:'Cormorant Garamond',Georgia,serif;font-size:30px;font-weight:300;letter-spacing:.06em}
.word b{color:#6c63ff;font-weight:300}
@media(max-width:700px){
aside{position:fixed;z-index:30;top:0;bottom:0;left:0;width:82vw;max-width:310px;transform:translateX(-100%);transition:transform .25s}
body.menu aside{transform:none;box-shadow:0 0 40px rgba(0,0,0,.7)}
body.menu .scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:20}
#top{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid #222}
#top button{background:#222;padding:6px 12px;font-size:20px;line-height:1}
#top .logo{padding:0}
.u{margin-left:8%}.a{margin-right:2%}#log{padding:12px}
}
</style>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%23050508'/%3E%3Cpolygon points='50,6 94,50 50,94 6,50' fill='none' stroke='%239a92ff' stroke-width='5' stroke-linejoin='round'/%3E%3Cpath d='M39 27 L28 77 M60.4 27 L71 77 M39 27 L49.7 43 L60.4 27 M32.6 59 H46.4 M53.6 59 H67.4' fill='none' stroke='%239a92ff' stroke-width='6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"></script>
</head><body>
<div class="scrim" id="scrim"></div>
<aside><div class="logo"><span class="mark"><svg viewBox="0 0 100 100" width="46" height="46" aria-hidden="true"><polygon points="50,4 96,50 50,96 4,50" fill="none" stroke="#9a92ff" stroke-width="3.2" stroke-linejoin="round"/><path d="M39 26.7 L27.9 77.6 M60.4 26.7 L70.8 77.6 M39 26.7 L49.7 43 L60.4 26.7 M32.6 59 H46.4 M53.6 59 H67.4" fill="none" stroke="#9a92ff" stroke-width="4.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="word">AA<b>.</b></span></div><button id="new">+ Nouvelle conversation</button><div id="list"></div>
<div class="me"><span id="uname"></span><button id="out">Déconnexion</button></div></aside>
<main>
<div id="top"><button id="menu" aria-label="Menu">&#9776;</button><div class="logo"><span class="mark"><svg viewBox="0 0 100 100" width="46" height="46" aria-hidden="true"><polygon points="50,4 96,50 50,96 4,50" fill="none" stroke="#9a92ff" stroke-width="3.2" stroke-linejoin="round"/><path d="M39 26.7 L27.9 77.6 M60.4 26.7 L70.8 77.6 M39 26.7 L49.7 43 L60.4 26.7 M32.6 59 H46.4 M53.6 59 H67.4" fill="none" stroke="#9a92ff" stroke-width="4.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="word">AA<b>.</b></span></div></div>
<div id="log"></div>
<div id="prev" style="display:none;max-width:800px;width:100%;margin:0 auto;padding:0 12px;box-sizing:border-box">
<img id="pimg" style="height:70px;border-radius:8px;vertical-align:middle"><span id="pname"></span> <button type="button" id="px" style="background:#444;padding:4px 10px">&times;</button></div>
<form id="f"><button type="button" id="att" title="Joindre un fichier (image, PDF, Excel, CSV...)" style="background:#444">&#128206;</button>
<input type="file" id="file" accept="image/*,.pdf,.xlsx,.xlsm,.csv,.txt,.md,.json,.py" hidden>
<input id="q" placeholder="Pose ta question... (joins une image, un PDF ou un Excel)" autofocus autocomplete="off">
<button>Envoyer</button></form>
</main>
<script>
const $=id=>document.getElementById(id);
const log=$('log'),q=$('q'),prev=$('prev'),pimg=$('pimg'),pname=$('pname'),file=$('file');
let image=null,att=null,busy=false,convId=null,list=[];
function render(el,t){if(window.marked&&window.DOMPurify){el.innerHTML=DOMPurify.sanitize(marked.parse(t,{breaks:true}))}else{el.style.whiteSpace='pre-wrap';el.textContent=t}}
function add(c,t,img,label){const d=document.createElement('div');d.className='m '+c;if(img){const i=document.createElement('img');i.src=img;i.style='max-height:160px;border-radius:8px;display:block;margin-bottom:6px';d.appendChild(i)}if(label)d.appendChild(document.createTextNode('\u{1F4CE} '+label+'\n'));d.appendChild(document.createTextNode(t));log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function closeMenu(){document.body.classList.remove('menu')}
async function copyText(t,btn){try{await navigator.clipboard.writeText(t)}catch(e){const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}btn.textContent='Copié \u2713';setTimeout(()=>btn.textContent='Copier',1500)}
function addTools(el,text){const d=document.createElement('div');d.className='tools';const b=document.createElement('button');b.type='button';b.textContent='Copier';b.onclick=()=>copyText(text,b);d.appendChild(b);el.appendChild(d)}
function typeInto(el,text,done){const parts=text.split(/(\s+)/);const per=Math.max(1,Math.ceil(parts.length/90));let i=0;
(function tick(){i=Math.min(parts.length,i+per);render(el,parts.slice(0,i).join(''));log.scrollTop=log.scrollHeight;if(i<parts.length)setTimeout(tick,22);else if(done)done()})()}
function statusFor(t,a,img){if(a){if(/\.(xlsx|xlsm|csv)$/i.test(a.name))return 'Traitement du fichier Excel\u2026';if(/\.pdf$/i.test(a.name))return 'Lecture du PDF\u2026';return 'Lecture du fichier\u2026'}
if(img)return 'Analyse de l\u2019image\u2026';if(/lettre|\bcv\b|rapport|word|pdf|document|contrat|devis/i.test(t))return 'Création du document\u2026';return 'Réflexion\u2026'}
function links(el,names){names.forEach(n=>{const l=document.createElement('a');l.className='dl';l.href='/download?c='+convId+'&f='+encodeURIComponent(n);l.textContent='⬇ '+n;l.download=n;el.appendChild(l)})}
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',body:JSON.stringify(body)});if(r.status===401){location.reload();throw new Error('Session expirée')}return r.json()}
function renderList(){const box=$('list');box.innerHTML='';
if(!list.length){box.innerHTML='<div class="empty">Aucune conversation enregistrée</div>';return}
list.forEach(c=>{const d=document.createElement('div');d.className='item'+(c.id===convId?' on':'');
const s=document.createElement('span');s.textContent=c.title;d.appendChild(s);
const x=document.createElement('b');x.textContent='×';x.title='Supprimer';
x.onclick=async e=>{e.stopPropagation();if(!confirm('Supprimer cette conversation ?'))return;await api('/api/delete',{id:c.id});if(c.id===convId)newChat();await refresh()};
const e=document.createElement('i');e.textContent='\u270E';e.title='Renommer';
e.onclick=async ev=>{ev.stopPropagation();const t=prompt('Nouveau titre :',c.title);if(t&&t.trim()){await api('/api/rename',{id:c.id,title:t.trim()});await refresh()}};
const act=document.createElement('span');act.className='act';act.appendChild(e);act.appendChild(x);d.appendChild(act);
d.onclick=()=>{if(c.id!==convId&&!busy){closeMenu();openConv(c.id)}};box.appendChild(d)})}
async function refresh(){list=(await api('/api/conversations')).list;renderList()}
function remember(){try{convId?localStorage.setItem('last',convId):localStorage.removeItem('last')}catch(e){}}
function newChat(){closeMenu();convId=null;log.innerHTML='';clearAtt();renderList();remember();q.focus()}
async function openConv(id){const s=await api('/api/conversation?id='+id);if(s.error){newChat();return}
convId=s.id;log.innerHTML='';clearAtt();
s.messages.forEach(m=>{const d=add(m.role==='user'?'u':'a',m.text);if(m.role!=='user'){render(d,m.text);addTools(d,m.text)}});
if(s.downloads.length){const d=add('a','\u{1F4C1} Fichiers de cette conversation :\n');links(d,s.downloads)}
renderList();remember();log.scrollTop=log.scrollHeight;q.focus()}
function setImage(f){const img=new Image();img.onload=()=>{const s=Math.min(1,1280/Math.max(img.width,img.height)),c=document.createElement('canvas');c.width=img.width*s;c.height=img.height*s;c.getContext('2d').drawImage(img,0,0,c.width,c.height);image=c.toDataURL('image/jpeg',0.85);pimg.src=image;pimg.style.display='';pname.textContent='';prev.style.display='block'};img.src=URL.createObjectURL(f)}
function setFile(f){const fr=new FileReader();fr.onload=()=>{att={name:f.name,data:fr.result.split(',')[1]};pimg.style.display='none';pname.textContent='\u{1F4CE} '+f.name;prev.style.display='block'};fr.readAsDataURL(f)}
function setAny(f){if(!f)return;clearAtt();f.type.startsWith('image/')?setImage(f):setFile(f)}
function clearAtt(){image=null;att=null;prev.style.display='none';file.value=''}
$('att').onclick=()=>file.click();
file.onchange=()=>setAny(file.files[0]);
$('px').onclick=clearAtt;
$('new').onclick=()=>{if(!busy)newChat()};
$('menu').onclick=()=>document.body.classList.toggle('menu');$('scrim').onclick=closeMenu;
$('out').onclick=async()=>{await fetch('/api/logout',{method:'POST',body:'{}'});try{localStorage.removeItem('last')}catch(e){}location.reload()};
document.addEventListener('paste',e=>{for(const it of e.clipboardData.items)if(it.type.startsWith('image/')){setAny(it.getAsFile());break}});
$('f').onsubmit=async e=>{e.preventDefault();if(busy)return;const t=q.value.trim();if(!t&&!image&&!att)return;q.value='';
const img=image,a=att;clearAtt();add('u',t,img,a&&a.name);const w=add('a','');w.className='m a status';w.textContent=statusFor(t,a,img);busy=true;
try{const r=await api('/ask',{conv:convId,q:t,image:img,file:a});
w.className='m a';w.textContent='';
if(r.id){convId=r.id;remember()}
if(r.list){list=r.list;renderList()}
if(r.error){render(w,'Erreur : '+r.error)}
else await new Promise(res=>typeInto(w,r.answer,()=>{if(r.downloads&&r.downloads.length)links(w,r.downloads);addTools(w,r.answer);res()}))}
catch(err){w.className='m a';render(w,'Erreur : '+err)}
busy=false;log.scrollTop=log.scrollHeight};
(async()=>{const me=await api('/api/me');$('uname').textContent=me.username;await refresh();
let last=null;try{last=localStorage.getItem('last')}catch(e){}
if(last&&list.some(c=>c.id===last))openConv(last);else q.focus()})();
</script></body></html>"""

LOGIN_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mon IA - Connexion</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{width:340px;max-width:92vw;background:#1a1a1a;border:1px solid #2c2c2c;border-radius:14px;padding:28px}
.card{--logo-bg:#1a1a1a}
.logo{display:flex;align-items:center;gap:12px;text-decoration:none;color:#fff;padding:0 0 14px}
.mark{width:46px;height:46px;flex:none;display:block;filter:drop-shadow(0 0 5px rgba(120,108,255,.9)) drop-shadow(0 0 12px rgba(108,99,255,.55));transition:filter .4s}
.mark svg{display:block}
.logo:hover .mark{filter:drop-shadow(0 0 7px rgba(140,128,255,1)) drop-shadow(0 0 18px rgba(108,99,255,.8))}
.word{font-family:'Cormorant Garamond',Georgia,serif;font-size:30px;font-weight:300;letter-spacing:.08em}
.word b{color:#6c63ff;font-weight:300}
h1{margin:0 0 4px;font-size:22px}.sub{color:#999;font-size:14px;margin-bottom:20px}
.tabs{display:flex;gap:6px;margin-bottom:16px}
.tabs button{flex:1;padding:9px;border-radius:8px;border:1px solid #333;background:#111;color:#bbb;cursor:pointer}
.tabs button.on{background:#2a4d8f;border-color:#2a4d8f;color:#fff}
label{display:block;font-size:13px;color:#aaa;margin:12px 0 5px}
input{width:100%;box-sizing:border-box;padding:11px;border-radius:8px;border:1px solid #444;background:#111;color:#eee;font-size:16px}
.go{width:100%;margin-top:18px;padding:12px;border:0;border-radius:8px;background:#2a4d8f;color:#fff;font-size:16px;cursor:pointer}
.err{color:#ff7b7b;font-size:14px;margin-top:12px;min-height:18px}
</style>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%23050508'/%3E%3Cpolygon points='50,6 94,50 50,94 6,50' fill='none' stroke='%239a92ff' stroke-width='5' stroke-linejoin='round'/%3E%3Cpath d='M39 27 L28 77 M60.4 27 L71 77 M39 27 L49.7 43 L60.4 27 M32.6 59 H46.4 M53.6 59 H67.4' fill='none' stroke='%239a92ff' stroke-width='6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300&display=swap" rel="stylesheet">
</head><body>
<form class="card" id="f">
<div class="logo"><span class="mark"><svg viewBox="0 0 100 100" width="46" height="46" aria-hidden="true"><polygon points="50,4 96,50 50,96 4,50" fill="none" stroke="#9a92ff" stroke-width="3.2" stroke-linejoin="round"/><path d="M39 26.7 L27.9 77.6 M60.4 26.7 L70.8 77.6 M39 26.7 L49.7 43 L60.4 26.7 M32.6 59 H46.4 M53.6 59 H67.4" fill="none" stroke="#9a92ff" stroke-width="4.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="word">AA<b>.</b></span></div><h1>Mon IA</h1><div class="sub">Ton assistant personnel, avec ton propre historique.</div>
<div class="tabs"><button type="button" id="t1" class="on">Connexion</button><button type="button" id="t2">Créer un compte</button></div>
<label for="u">Nom d'utilisateur</label><input id="u" autocomplete="username" required maxlength="30" autofocus>
<label for="p">Mot de passe</label><input id="p" type="password" autocomplete="current-password" required>
<div id="cw" style="display:none"><label for="c">Code d'invitation</label><input id="c" autocomplete="off"></div>
<button class="go" id="go">Se connecter</button><div class="err" id="err"></div>
</form>
<script>
const $=id=>document.getElementById(id);let mode='login',cfg={};
function setMode(m){mode=m;$('t1').className=m==='login'?'on':'';$('t2').className=m==='signup'?'on':'';
$('go').textContent=m==='login'?'Se connecter':'Créer mon compte';$('cw').style.display=(m==='signup'&&cfg.needs_code)?'block':'none';
$('p').autocomplete=m==='login'?'current-password':'new-password';$('err').textContent=''}
$('t1').onclick=()=>setMode('login');$('t2').onclick=()=>setMode('signup');
fetch('/api/config').then(r=>r.json()).then(c=>{cfg=c;if(!c.signup)$('t2').style.display='none'});
$('f').onsubmit=async e=>{e.preventDefault();$('err').textContent='';
const r=await fetch('/api/'+mode,{method:'POST',body:JSON.stringify({username:$('u').value,password:$('p').value,code:$('c').value})});
const d=await r.json();if(d.error)$('err').textContent=d.error;else location.reload()};
</script></body></html>"""

CTYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}

# ---------- mots de passe (scrypt, bibliothèque standard) ----------
def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, bytes.fromhex(h))
    except Exception:
        return False


DUMMY_HASH = hash_pw("dummy-password")  # temps de calcul identique si l'utilisateur n'existe pas

# ---------- limitation des tentatives (en mémoire) ----------
_attempts: dict[str, list[float]] = {}


def throttled(key: str, limit: int = 8, window: int = 600) -> bool:
    now = time.time()
    recent = [t for t in _attempts.get(key, []) if now - t < window]
    if len(recent) >= limit:
        _attempts[key] = recent
        return True
    recent.append(now)
    _attempts[key] = recent
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "MonIA"

    # ----- utilitaires -----
    def _send(self, body: bytes, ctype="application/json", code=200, headers=None):
        self.send_response(code)
        binary = ctype.startswith(("application/vnd", "application/pdf", "application/octet"))
        self.send_header("Content-Type", ctype if binary else ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, headers=None):
        self._send(json.dumps(obj).encode(), code=code, headers=headers)

    def _token(self) -> str:
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c["session"].value if "session" in c else ""

    def _user(self):
        return db.user_for_token(self._token())

    def _ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "")
        return (fwd.split(",")[0].strip() if fwd else self.client_address[0]) or "?"

    def _cookie(self, token: str, max_age: int) -> dict:
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return {"Set-Cookie": f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}{secure}"}

    def _route(self):
        """(chemin, paramètres). Sur Vercel, toutes les URL sont réécrites vers /api/index ;
        le chemin d'origine arrive dans le paramètre __p (voir vercel.json)."""
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        path = qs.pop("__p", [url.path])[0]
        if not path.startswith("/") or path.startswith("/api/index"):
            path = "/"
        return path, qs

    # ----- GET -----
    def do_GET(self):
        path, qs = self._route()
        if path == "/api/config":
            return self._json({"needs_code": bool(SIGNUP_CODE), "signup": ALLOW_SIGNUP})
        user = self._user()
        if path == "/":
            return self._send((PAGE if user else LOGIN_PAGE).encode(), "text/html")
        if not user:
            return self._json({"error": "Non connecté"}, 401)
        if path == "/api/me":
            return self._json({"username": user.username})
        if path == "/api/conversations":
            return self._json({"list": db.list_convs(user.id)})
        if path == "/api/conversation":
            try:
                cid = qs.get("id", [""])[0]
                if not ID_RE.match(cid):
                    raise ValueError
                chat = Chat(user.id, cid)
            except Exception:
                return self._json({"error": "Conversation introuvable"}, 404)
            return self._json({"id": chat.conv_id, "messages": chat.messages(), "downloads": chat.outputs()})
        if path == "/download":
            cid, name = qs.get("c", [""])[0], qs.get("f", [""])[0]
            if not ID_RE.match(cid) or not db.get_conv(user.id, cid):  # la conversation doit être la sienne
                return self._send(b"Introuvable", "text/plain", 404)
            data = db.get_file(cid, name)
            if data is None or name == "current.xlsx":
                return self._send(b"Introuvable", "text/plain", 404)
            ext = os.path.splitext(name)[1].lower()
            return self._send(
                data, CTYPES.get(ext, "application/octet-stream"),
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
            )
        self._send(b"Introuvable", "text/plain", 404)

    # ----- POST -----
    def do_POST(self):
        self.path, _ = self._route()
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self._json({"error": "Origine refusée"}, 403)  # protection CSRF
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            return self._json({"error": f"Fichier trop volumineux ({MAX_BODY // (1024 * 1024) * 3 // 4} Mo max)."}, 413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "Requête invalide"}, 400)

        if self.path in ("/api/signup", "/api/login"):
            return self._auth(data)
        if self.path == "/api/logout":
            db.delete_session(self._token())
            return self._json({}, headers=self._cookie("", 0))

        user = self._user()
        if not user:
            return self._json({"error": "Non connecté"}, 401)
        if self.path == "/api/delete":
            cid = data.get("id", "")
            if ID_RE.match(cid):
                db.delete_conv(user.id, cid)
            return self._json({})
        if self.path == "/api/rename":
            cid, title = data.get("id", ""), str(data.get("title", "")).strip()[:80]
            if ID_RE.match(cid) and title:
                db.rename_conv(user.id, cid, title)
            return self._json({})
        if self.path == "/ask":
            return self._json(self._ask(user, data))
        self._json({"error": "Introuvable"}, 404)

    def _auth(self, data):
        mode = self.path.rsplit("/", 1)[1]
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))
        if throttled(f"{self._ip()}|{mode}", 10 if mode == "login" else 5):
            return self._json({"error": "Trop de tentatives. Réessaie dans quelques minutes."}, 429)
        if mode == "signup":
            if not ALLOW_SIGNUP:
                return self._json({"error": "Les inscriptions sont fermées."}, 403)
            if SIGNUP_CODE and not hmac.compare_digest(str(data.get("code", "")), SIGNUP_CODE):
                return self._json({"error": "Code d'invitation incorrect."}, 403)
            if not USER_RE.match(username):
                return self._json({"error": "Nom d'utilisateur : 3 à 30 caractères (lettres, chiffres, . _ -)."})
            if len(password) < 8:
                return self._json({"error": "Mot de passe : 8 caractères minimum."})
            uid = db.create_user(username, hash_pw(password))
            if not uid:
                return self._json({"error": "Ce nom d'utilisateur est déjà pris."})
        else:
            row = db.get_user_by_name(username)
            ok = check_pw(password, row.pw_hash if row else DUMMY_HASH)
            if not (row and ok):
                return self._json({"error": "Nom d'utilisateur ou mot de passe incorrect."})
            uid = row.id
        token = db.create_session(uid)
        self._json({"ok": True}, headers=self._cookie(token, 30 * 86400))

    def _ask(self, user, data) -> dict:
        if DAILY_LIMIT and db.bump_usage(user.id) > DAILY_LIMIT:
            return {"error": f"Limite quotidienne atteinte ({DAILY_LIMIT} messages). Reviens demain."}
        try:
            cid = data.get("conv") or None
            if cid and not ID_RE.match(cid):
                raise ValueError("Conversation introuvable")
            chat = Chat(user.id, cid)
            f = data.get("file")
            file = (f["name"], base64.b64decode(f["data"])) if f else None
            answer, provider = chat.ask(str(data.get("q", "")), data.get("image"), file)
            return {
                "answer": answer,
                "provider": provider,
                "downloads": chat.turn_files,
                "id": chat.conv_id,
                "list": db.list_convs(user.id),
            }
        except Exception as e:
            return {"error": str(e)}

    def log_message(self, fmt, *args):  # logs sobres (pas de contenu sensible)
        if os.getenv("ACCESS_LOG"):
            super().log_message(fmt, *args)


def main():
    if not available_providers():
        sys.exit("Aucune clé API (GROQ_API_KEY, GEMINI_API_KEY...) : voir .env.example")
    if sys.platform.startswith("linux"):
        # Les autres processus (ex. scripts Excel) ne peuvent plus lire notre mémoire/environnement
        try:
            import ctypes

            ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 0
        except Exception:
            pass
    db.init()
    print(f"Ouvre http://localhost:{PORT}" if not ONLINE else f"Serveur en ligne sur le port {PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
