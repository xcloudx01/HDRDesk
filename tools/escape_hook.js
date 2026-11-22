// Log every D3DKMTEscape (kernel-graphics escape, the transport NvAPI uses) with its in/out private data,
// plus any nvapi_QueryInterface lookups made while we're attached.
const MAX = 16384;
const esc = Process.getModuleByName('win32u.dll').getExportByName('NtGdiDdDDIEscape');
Interceptor.attach(esc, {
  onEnter(args) {
    const p = args[0];
    this.hA = p.readU32();
    this.hDev = p.add(4).readU32();
    this.hCtx = p.add(28).readU32();
    this.type = p.add(8).readU32();
    this.flags = p.add(12).readU32();
    this.data = p.add(16).readPointer();
    this.size = p.add(24).readU32();
    this.inBuf = (this.size > 0 && this.size <= MAX && !this.data.isNull()) ? this.data.readByteArray(this.size) : null;
    this.t = Date.now();
  },
  onLeave(ret) {
    if (!this.inBuf) return;
    // keep only NVDA escapes with the 0x0100003B command (RTX Video settings) to stay small
    const u = new Uint32Array(this.inBuf.slice(0, Math.min(this.size, 20)).byteLength >= 20 ? this.inBuf.slice(0, 20) : new ArrayBuffer(20));
    if (u[4] !== 0x0100003b) return;
    const out = this.data.readByteArray(this.size);
    const both = new Uint8Array(this.size * 2);
    both.set(new Uint8Array(this.inBuf), 0);
    both.set(new Uint8Array(out), this.size);
    send({ k: 'esc', t: this.t, tid: Process.getCurrentThreadId(), hA: this.hA, hDev: this.hDev, hCtx: this.hCtx, type: this.type,
           flags: this.flags, size: this.size, ret: ret.toInt32() }, both.buffer);
  }
});

const nv = Process.findModuleByName('nvapi64.dll');
if (nv) {
  const qi = nv.findExportByName('nvapi_QueryInterface');
  if (qi) {
    Interceptor.attach(qi, {
      onEnter(args) { this.id = args[0].toUInt32(); },
      onLeave(ret) { send({ k: 'qi', t: Date.now(), id: '0x' + this.id.toString(16), fn: ret.toString() }); }
    });
  }
}
send({ k: 'ready', pid: Process.id, nvapi: nv ? nv.base.toString() : null });
