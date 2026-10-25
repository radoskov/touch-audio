"""Authenticated LAN controller. Flask threads never touch Qt/VLC directly."""
from __future__ import annotations
from concurrent.futures import TimeoutError
from functools import wraps
import hmac
import logging
import threading
from flask import Flask, Response, jsonify, request, send_file
from werkzeug.serving import make_server

HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Touch Audio · Remote</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0d1725;color:#eaf4ff}
*{box-sizing:border-box}body{margin:0 auto;max-width:760px;padding:20px}h1{font-size:1.45rem;margin:0 0 8px}
.panel{border:1px solid #2d4459;border-radius:16px;padding:18px;margin:14px 0;background:#162536}
button,input{font:inherit;border-radius:10px;border:1px solid #4d6277;padding:11px;color:#f4faff;background:#20374d}
button{cursor:pointer;min-height:46px}button:active{background:#2875aa}button[aria-pressed=true]{border:2px solid #8ae7fa;background:#126f8a}input{width:100%}
.controls{display:flex;flex-wrap:wrap;gap:9px;align-items:center}.controls button{flex:1}
input[type=range]{accent-color:#42bdda;padding:0}small,.muted{color:#a4bbc9}
.item{display:block;width:100%;text-align:left;margin:6px 0;overflow-wrap:anywhere}
#searchresults{max-height:320px;overflow:auto}#error{color:#ffb5b5;white-space:pre-wrap}
</style></head><body>
<h1>♫ Touch Audio</h1><div class="panel" id="login"><label>Access token (from the Raspberry Pi configuration)</label>
<input id="token" type="password" autocomplete="off" placeholder="Paste LAN token"><button id="connect" style="margin-top:10px">Connect</button></div>
<div id="app" hidden><div class="panel"><h2 id="title" style="margin-top:0">Player</h2><p id="subtitle" class="muted"></p>
<p id="track"></p><div class="controls"><button data-action="previous">⏮ Previous</button><button data-action="toggle">⏯ Play / Pause</button>
<button data-action="next">Next ⏭</button><button data-action="stop">■ Stop</button></div>
<div class="controls" style="margin-top:12px"><button id="repeatFile" aria-pressed="false">🔂 Repeat file</button>
<button id="repeatAlbum" aria-pressed="false">🔁 Repeat album</button></div>
<p><label>Volume <span id="volumeValue"></span>%</label><input id="volume" type="range" min="0" max="100"></p>
<p><label>Position <span id="positionValue"></span></label><input id="seek" type="range" min="0" max="1000" value="0"></p>
</div><div class="panel"><h3>Search books, albums and tracks</h3><input id="query" placeholder="Filename, title, artist or album">
<div id="searchresults"></div></div>
<div class="panel"><h3>Sleep / shutdown timer</h3><p id="timerstatus" class="muted"></p>
<div class="controls"><input id="minutes" style="width:110px;flex:1" type="number" min="1" max="1440" value="30" aria-label="Minutes"><button id="startTimer">Start timer (minutes)</button><button id="cancelTimer">Cancel</button></div>
</div><div class="panel"><h3>Display controls</h3>
<p><button id="dimScreen">☼ Dim / restore screen</button></p>
<p><label>Brightness <span id="brightnessValue"></span>%</label><input id="brightness" type="range" min="10" max="100"></p>
<p class="muted" id="brightnessMode"></p>
<hr style="border:0;border-top:2px solid #5a4049;margin:18px 0">
<button id="shutdown" style="width:100%;background:#5a2028;border:2px solid #d98691">⏻ Shut down computer</button>
</div></div>
<p id="error"></p><small>Only use this controller on a trusted LAN. No TLS is provided.</small>
<script>
const $=id=>document.getElementById(id);let token=sessionStorage.getItem('touch_audio_token')||'';let lastState=null;let busySeek=false;let busyVolume=false;let busyBrightness=false;let fetchingState=false;
async function api(path,method='GET',data){
 let r=await fetch('/api/'+path,{method,headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
 let j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j;
}
function fmt(sec){sec=Math.floor(Number(sec)||0);return Math.floor(sec/3600)>0?`${Math.floor(sec/3600)}:${String(Math.floor(sec%3600/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`:`${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`}
async function refresh(){if(fetchingState)return;fetchingState=true;try{let s=await api('state');lastState=s;$('title').textContent=s.entry?.display_name||'No entry selected';
$('subtitle').textContent=s.entry?.subtitle||'';$('track').textContent=s.track?`${s.track.filename}${s.track.title?' · '+s.track.title:''}`:'No file selected';
if(!busyVolume){$('volume').value=s.playback.volume}$('volumeValue').textContent=s.playback.volume;
if(s.brightness){if(!busyBrightness)$('brightness').value=s.brightness.normal_percent;
$('brightnessValue').textContent=s.brightness.normal_percent;
$('brightnessMode').textContent=(s.brightness.backend==='hardware'?'Hardware backlight':'Software (app only)')+(s.brightness.dimmed?' · Dimmed':'');
$('dimScreen').setAttribute('aria-pressed',String(s.brightness.dimmed));}
if(!busySeek){$('seek').value=s.playback.duration?Math.round(1000*s.playback.position/s.playback.duration):0;}
$('positionValue').textContent=fmt(s.playback.position)+' / '+fmt(s.playback.duration);
$('repeatFile').setAttribute('aria-pressed',String(s.playback.repeat_mode==='file'));
$('repeatAlbum').setAttribute('aria-pressed',String(s.playback.repeat_mode==='album'));
$('timerstatus').textContent=s.timer.active?(s.timer.fading?'Fading volume · ':'Shutting down in ')+fmt(s.timer.remaining_seconds):'No timer active';
$('error').textContent='';}catch(e){$('error').textContent=e.message;}finally{fetchingState=false;}}
async function control(action,extra={}){try{await api('control','POST',{action,...extra});await refresh()}catch(e){$('error').textContent=e.message}}
$('connect').onclick=async()=>{token=$('token').value.trim();try{await api('state');sessionStorage.setItem('touch_audio_token',token);$('login').hidden=true;$('app').hidden=false;refresh()}catch(e){$('error').textContent='Incorrect token or server unavailable'}};
if(token){$('token').value=token;$('connect').click()}
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>control(b.dataset.action));
$('repeatFile').onclick=()=>control('repeat',{mode:lastState?.playback.repeat_mode==='file'?'off':'file'});
$('repeatAlbum').onclick=()=>control('repeat',{mode:lastState?.playback.repeat_mode==='album'?'off':'album'});
$('volume').oninput=()=>{$('volumeValue').textContent=$('volume').value;busyVolume=true};
$('volume').onchange=()=>{busyVolume=false;control('volume',{value:Number($('volume').value)})};
$('seek').oninput=()=>{busySeek=true;if(lastState)$('positionValue').textContent=fmt(lastState.playback.duration*Number($('seek').value)/1000)+' / '+fmt(lastState.playback.duration)};
$('seek').onchange=()=>{busySeek=false;control('seek',{seconds:lastState?lastState.playback.duration*Number($('seek').value)/1000:0})};
$('startTimer').onclick=()=>control('timer',{seconds:Math.max(1,Math.min(1440,Number($('minutes').value)||30))*60});
$('cancelTimer').onclick=()=>control('timer',{seconds:0});
$('dimScreen').onclick=()=>control('dim');
$('brightness').oninput=()=>{$('brightnessValue').textContent=$('brightness').value;busyBrightness=true};
$('brightness').onchange=()=>{busyBrightness=false;control('brightness',{value:Number($('brightness').value)})};
$('shutdown').onclick=()=>{if(window.confirm('Shut down the entire computer now? All other programs will be closed.'))control('shutdown',{confirm:true})};
let searchTimeout;
$('query').oninput=()=>{clearTimeout(searchTimeout);searchTimeout=setTimeout(async()=>{let q=$('query').value.trim();let area=$('searchresults');area.replaceChildren();if(!q)return;
try{let results=await api('search?q='+encodeURIComponent(q));results.results.forEach(item=>{let b=document.createElement('button');b.className='item';
let label=item.type==='track'?`♫ ${item.file.filename}${item.file.title?' · '+item.file.title:''} — ${item.entry.folder_name}`:`▣ ${item.entry.folder_name}${item.entry.album_title?' · '+item.entry.album_title:''}`;
b.textContent=label;b.onclick=async()=>{await control('select',{entry_id:item.entry.id,file_index:item.file_index??0});};area.append(b)});
if(!results.results.length)area.textContent='No results.'}catch(e){$('error').textContent=e.message}},220)};
// No requests while the tab is hidden; paused players need fewer polls.
function pollLoop(){if(!$('app').hidden && !document.hidden)refresh();
setTimeout(pollLoop,document.hidden?10000:(lastState?.playback.status==='playing'?2000:5000));}
pollLoop();
</script></body></html>'''


def make_app(send, token: str) -> Flask:
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16384

    def auth(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            supplied = request.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied, 'Bearer ' + token):
                return jsonify(error='Unauthorized'), 401
            return fn(*args, **kwargs)
        return wrapper

    def dispatch(payload):
        try:
            return send(payload)
        except TimeoutError:
            return {'error': 'GUI is busy or unavailable'}, 503
        except (ValueError, KeyError) as exc:
            return {'error': str(exc)}, 400
        except Exception as exc:
            app.logger.exception('Remote command failed')
            return {'error': 'Internal command error'}, 500

    @app.get('/')
    def home():
        return Response(HTML, mimetype='text/html')

    @app.get('/api/state')
    @auth
    def state():
        return dispatch({'action': 'state'})

    @app.get('/api/search')
    @auth
    def search():
        q = request.args.get('q', '')[:160]
        return dispatch({'action': 'search', 'query': q})

    @app.post('/api/control')
    @auth
    def control():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('action'), str):
            return jsonify(error='Expected JSON object with action'), 400
        if data['action'] not in {'play', 'pause', 'toggle', 'stop', 'next', 'previous',
                                  'volume', 'seek', 'select', 'timer', 'refresh', 'repeat',
                                  'dim', 'brightness', 'shutdown',
                                  'nav_up', 'nav_down', 'nav_left', 'nav_right', 'activate'}:
            return jsonify(error='Unknown action'), 400
        return dispatch(data)

    @app.get('/api/cover/<entry_id>')
    @auth
    def cover(entry_id):
        try:
            result = send({'action': 'cover_path', 'entry_id': entry_id})
            if not result.get('path'):
                return jsonify(error='Cover not found'), 404
            return send_file(result['path'], conditional=True)
        except Exception:
            return jsonify(error='Cover unavailable'), 404

    return app


class WebServer(threading.Thread):
    def __init__(self, host: str, port: int, app: Flask):
        super().__init__(daemon=True, name='lan-web-controller')
        self.host, self.port, self.app = host, port, app
        self.server = None
        self.error = None

    def run(self):
        try:
            self.server = make_server(self.host, self.port, self.app, threaded=True)
            self.server.serve_forever()
        except Exception as exc:
            self.error = str(exc)
            logging.exception('Unable to start LAN controller')

    def close(self):
        if self.server:
            self.server.shutdown()
