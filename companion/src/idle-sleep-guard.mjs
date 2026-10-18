// @ts-check
import { spawn } from 'node:child_process';

/** Hold macOS awake while an Agent direction is running, never while paused. With `display` (the artist's
 * "Keep the screen awake while painting"), the screen stays on too: Krita paints into the active view, which
 * it loses when the screen sleeps. `onChange` reports each hold so the panel can show it. */
export class IdleSleepGuard {
  constructor({enabled=process.platform==='darwin',spawnProcess=spawn,pid=process.pid,onError=/** @type {(error: any) => void} */ (()=>{}),
    display=/** @type {() => boolean} */ (()=>false),onChange=/** @type {(state: {active: boolean, display: boolean}) => void} */ (()=>{})}={}) {
    this.enabled=enabled; this.spawnProcess=spawnProcess; this.pid=pid; this.onError=onError;
    this.display=display; this.onChange=onChange;
    this.child=null;
  }
  start() {
    if (!this.enabled || this.child) return;
    const display=!!this.display();
    try {
      const child=this.spawnProcess('/usr/bin/caffeinate',[...(display?['-d']:[]),'-i','-w',String(this.pid)],{stdio:'ignore'});
      this.child=child;
      child.on('error',error=>{
        if (this.child===child) { this.child=null; this.onChange({active:false,display:false}); }
        this.onError(error);
      });
      child.on('exit',()=>{if (this.child===child) { this.child=null; this.onChange({active:false,display:false}); }});
      this.onChange({active:true,display});
    } catch(error) {this.onError(error);}
  }
  stop() {
    const child=this.child;
    this.child=null;
    if (child && child.exitCode===null && !child.killed) child.kill();
    if (child) this.onChange({active:false,display:false});
  }
}
