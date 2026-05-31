import { createRequire } from "node:module";
var __create = Object.create;
var __getProtoOf = Object.getPrototypeOf;
var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
function __accessProp(key) {
  return this[key];
}
var __toESMCache_node;
var __toESMCache_esm;
var __toESM = (mod, isNodeMode, target) => {
  var canCache = mod != null && typeof mod === "object";
  if (canCache) {
    var cache = isNodeMode ? __toESMCache_node ??= new WeakMap : __toESMCache_esm ??= new WeakMap;
    var cached = cache.get(mod);
    if (cached)
      return cached;
  }
  target = mod != null ? __create(__getProtoOf(mod)) : {};
  const to = isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target;
  for (let key of __getOwnPropNames(mod))
    if (!__hasOwnProp.call(to, key))
      __defProp(to, key, {
        get: __accessProp.bind(mod, key),
        enumerable: true
      });
  if (canCache)
    cache.set(mod, to);
  return to;
};
var __commonJS = (cb, mod) => () => (mod || cb((mod = { exports: {} }).exports, mod), mod.exports);
var __returnValue = (v) => v;
function __exportSetter(name, newValue) {
  this[name] = __returnValue.bind(null, newValue);
}
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: __exportSetter.bind(all, name)
    });
};
var __esm = (fn, res) => () => (fn && (res = fn(fn = 0)), res);
var __require = /* @__PURE__ */ createRequire(import.meta.url);

// node_modules/react/cjs/react.production.min.js
var require_react_production_min = __commonJS((exports) => {
  var l = Symbol.for("react.element");
  var n = Symbol.for("react.portal");
  var p = Symbol.for("react.fragment");
  var q = Symbol.for("react.strict_mode");
  var r = Symbol.for("react.profiler");
  var t = Symbol.for("react.provider");
  var u = Symbol.for("react.context");
  var v = Symbol.for("react.forward_ref");
  var w = Symbol.for("react.suspense");
  var x = Symbol.for("react.memo");
  var y = Symbol.for("react.lazy");
  var z = Symbol.iterator;
  function A(a) {
    if (a === null || typeof a !== "object")
      return null;
    a = z && a[z] || a["@@iterator"];
    return typeof a === "function" ? a : null;
  }
  var B = { isMounted: function() {
    return false;
  }, enqueueForceUpdate: function() {}, enqueueReplaceState: function() {}, enqueueSetState: function() {} };
  var C = Object.assign;
  var D = {};
  function E(a, b, e) {
    this.props = a;
    this.context = b;
    this.refs = D;
    this.updater = e || B;
  }
  E.prototype.isReactComponent = {};
  E.prototype.setState = function(a, b) {
    if (typeof a !== "object" && typeof a !== "function" && a != null)
      throw Error("setState(...): takes an object of state variables to update or a function which returns an object of state variables.");
    this.updater.enqueueSetState(this, a, b, "setState");
  };
  E.prototype.forceUpdate = function(a) {
    this.updater.enqueueForceUpdate(this, a, "forceUpdate");
  };
  function F() {}
  F.prototype = E.prototype;
  function G(a, b, e) {
    this.props = a;
    this.context = b;
    this.refs = D;
    this.updater = e || B;
  }
  var H = G.prototype = new F;
  H.constructor = G;
  C(H, E.prototype);
  H.isPureReactComponent = true;
  var I = Array.isArray;
  var J = Object.prototype.hasOwnProperty;
  var K = { current: null };
  var L = { key: true, ref: true, __self: true, __source: true };
  function M(a, b, e) {
    var d, c = {}, k = null, h = null;
    if (b != null)
      for (d in b.ref !== undefined && (h = b.ref), b.key !== undefined && (k = "" + b.key), b)
        J.call(b, d) && !L.hasOwnProperty(d) && (c[d] = b[d]);
    var g = arguments.length - 2;
    if (g === 1)
      c.children = e;
    else if (1 < g) {
      for (var f = Array(g), m = 0;m < g; m++)
        f[m] = arguments[m + 2];
      c.children = f;
    }
    if (a && a.defaultProps)
      for (d in g = a.defaultProps, g)
        c[d] === undefined && (c[d] = g[d]);
    return { $$typeof: l, type: a, key: k, ref: h, props: c, _owner: K.current };
  }
  function N(a, b) {
    return { $$typeof: l, type: a.type, key: b, ref: a.ref, props: a.props, _owner: a._owner };
  }
  function O(a) {
    return typeof a === "object" && a !== null && a.$$typeof === l;
  }
  function escape(a) {
    var b = { "=": "=0", ":": "=2" };
    return "$" + a.replace(/[=:]/g, function(a2) {
      return b[a2];
    });
  }
  var P = /\/+/g;
  function Q(a, b) {
    return typeof a === "object" && a !== null && a.key != null ? escape("" + a.key) : b.toString(36);
  }
  function R(a, b, e, d, c) {
    var k = typeof a;
    if (k === "undefined" || k === "boolean")
      a = null;
    var h = false;
    if (a === null)
      h = true;
    else
      switch (k) {
        case "string":
        case "number":
          h = true;
          break;
        case "object":
          switch (a.$$typeof) {
            case l:
            case n:
              h = true;
          }
      }
    if (h)
      return h = a, c = c(h), a = d === "" ? "." + Q(h, 0) : d, I(c) ? (e = "", a != null && (e = a.replace(P, "$&/") + "/"), R(c, b, e, "", function(a2) {
        return a2;
      })) : c != null && (O(c) && (c = N(c, e + (!c.key || h && h.key === c.key ? "" : ("" + c.key).replace(P, "$&/") + "/") + a)), b.push(c)), 1;
    h = 0;
    d = d === "" ? "." : d + ":";
    if (I(a))
      for (var g = 0;g < a.length; g++) {
        k = a[g];
        var f = d + Q(k, g);
        h += R(k, b, e, f, c);
      }
    else if (f = A(a), typeof f === "function")
      for (a = f.call(a), g = 0;!(k = a.next()).done; )
        k = k.value, f = d + Q(k, g++), h += R(k, b, e, f, c);
    else if (k === "object")
      throw b = String(a), Error("Objects are not valid as a React child (found: " + (b === "[object Object]" ? "object with keys {" + Object.keys(a).join(", ") + "}" : b) + "). If you meant to render a collection of children, use an array instead.");
    return h;
  }
  function S(a, b, e) {
    if (a == null)
      return a;
    var d = [], c = 0;
    R(a, d, "", "", function(a2) {
      return b.call(e, a2, c++);
    });
    return d;
  }
  function T(a) {
    if (a._status === -1) {
      var b = a._result;
      b = b();
      b.then(function(b2) {
        if (a._status === 0 || a._status === -1)
          a._status = 1, a._result = b2;
      }, function(b2) {
        if (a._status === 0 || a._status === -1)
          a._status = 2, a._result = b2;
      });
      a._status === -1 && (a._status = 0, a._result = b);
    }
    if (a._status === 1)
      return a._result.default;
    throw a._result;
  }
  var U = { current: null };
  var V = { transition: null };
  var W = { ReactCurrentDispatcher: U, ReactCurrentBatchConfig: V, ReactCurrentOwner: K };
  function X() {
    throw Error("act(...) is not supported in production builds of React.");
  }
  exports.Children = { map: S, forEach: function(a, b, e) {
    S(a, function() {
      b.apply(this, arguments);
    }, e);
  }, count: function(a) {
    var b = 0;
    S(a, function() {
      b++;
    });
    return b;
  }, toArray: function(a) {
    return S(a, function(a2) {
      return a2;
    }) || [];
  }, only: function(a) {
    if (!O(a))
      throw Error("React.Children.only expected to receive a single React element child.");
    return a;
  } };
  exports.Component = E;
  exports.Fragment = p;
  exports.Profiler = r;
  exports.PureComponent = G;
  exports.StrictMode = q;
  exports.Suspense = w;
  exports.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED = W;
  exports.act = X;
  exports.cloneElement = function(a, b, e) {
    if (a === null || a === undefined)
      throw Error("React.cloneElement(...): The argument must be a React element, but you passed " + a + ".");
    var d = C({}, a.props), c = a.key, k = a.ref, h = a._owner;
    if (b != null) {
      b.ref !== undefined && (k = b.ref, h = K.current);
      b.key !== undefined && (c = "" + b.key);
      if (a.type && a.type.defaultProps)
        var g = a.type.defaultProps;
      for (f in b)
        J.call(b, f) && !L.hasOwnProperty(f) && (d[f] = b[f] === undefined && g !== undefined ? g[f] : b[f]);
    }
    var f = arguments.length - 2;
    if (f === 1)
      d.children = e;
    else if (1 < f) {
      g = Array(f);
      for (var m = 0;m < f; m++)
        g[m] = arguments[m + 2];
      d.children = g;
    }
    return { $$typeof: l, type: a.type, key: c, ref: k, props: d, _owner: h };
  };
  exports.createContext = function(a) {
    a = { $$typeof: u, _currentValue: a, _currentValue2: a, _threadCount: 0, Provider: null, Consumer: null, _defaultValue: null, _globalName: null };
    a.Provider = { $$typeof: t, _context: a };
    return a.Consumer = a;
  };
  exports.createElement = M;
  exports.createFactory = function(a) {
    var b = M.bind(null, a);
    b.type = a;
    return b;
  };
  exports.createRef = function() {
    return { current: null };
  };
  exports.forwardRef = function(a) {
    return { $$typeof: v, render: a };
  };
  exports.isValidElement = O;
  exports.lazy = function(a) {
    return { $$typeof: y, _payload: { _status: -1, _result: a }, _init: T };
  };
  exports.memo = function(a, b) {
    return { $$typeof: x, type: a, compare: b === undefined ? null : b };
  };
  exports.startTransition = function(a) {
    var b = V.transition;
    V.transition = {};
    try {
      a();
    } finally {
      V.transition = b;
    }
  };
  exports.unstable_act = X;
  exports.useCallback = function(a, b) {
    return U.current.useCallback(a, b);
  };
  exports.useContext = function(a) {
    return U.current.useContext(a);
  };
  exports.useDebugValue = function() {};
  exports.useDeferredValue = function(a) {
    return U.current.useDeferredValue(a);
  };
  exports.useEffect = function(a, b) {
    return U.current.useEffect(a, b);
  };
  exports.useId = function() {
    return U.current.useId();
  };
  exports.useImperativeHandle = function(a, b, e) {
    return U.current.useImperativeHandle(a, b, e);
  };
  exports.useInsertionEffect = function(a, b) {
    return U.current.useInsertionEffect(a, b);
  };
  exports.useLayoutEffect = function(a, b) {
    return U.current.useLayoutEffect(a, b);
  };
  exports.useMemo = function(a, b) {
    return U.current.useMemo(a, b);
  };
  exports.useReducer = function(a, b, e) {
    return U.current.useReducer(a, b, e);
  };
  exports.useRef = function(a) {
    return U.current.useRef(a);
  };
  exports.useState = function(a) {
    return U.current.useState(a);
  };
  exports.useSyncExternalStore = function(a, b, e) {
    return U.current.useSyncExternalStore(a, b, e);
  };
  exports.useTransition = function() {
    return U.current.useTransition();
  };
  exports.version = "18.3.1";
});

// node_modules/react/index.js
var require_react = __commonJS((exports, module) => {
  if (true) {
    module.exports = require_react_production_min();
  } else {}
});

// node_modules/signal-exit/signals.js
var require_signals = __commonJS((exports, module) => {
  module.exports = [
    "SIGABRT",
    "SIGALRM",
    "SIGHUP",
    "SIGINT",
    "SIGTERM"
  ];
  if (process.platform !== "win32") {
    module.exports.push("SIGVTALRM", "SIGXCPU", "SIGXFSZ", "SIGUSR2", "SIGTRAP", "SIGSYS", "SIGQUIT", "SIGIOT");
  }
  if (process.platform === "linux") {
    module.exports.push("SIGIO", "SIGPOLL", "SIGPWR", "SIGSTKFLT", "SIGUNUSED");
  }
});

// node_modules/signal-exit/index.js
var require_signal_exit = __commonJS((exports, module) => {
  var process3 = global.process;
  var processOk = function(process4) {
    return process4 && typeof process4 === "object" && typeof process4.removeListener === "function" && typeof process4.emit === "function" && typeof process4.reallyExit === "function" && typeof process4.listeners === "function" && typeof process4.kill === "function" && typeof process4.pid === "number" && typeof process4.on === "function";
  };
  if (!processOk(process3)) {
    module.exports = function() {
      return function() {};
    };
  } else {
    assert = __require("assert");
    signals = require_signals();
    isWin = /^win/i.test(process3.platform);
    EE = __require("events");
    if (typeof EE !== "function") {
      EE = EE.EventEmitter;
    }
    if (process3.__signal_exit_emitter__) {
      emitter = process3.__signal_exit_emitter__;
    } else {
      emitter = process3.__signal_exit_emitter__ = new EE;
      emitter.count = 0;
      emitter.emitted = {};
    }
    if (!emitter.infinite) {
      emitter.setMaxListeners(Infinity);
      emitter.infinite = true;
    }
    module.exports = function(cb, opts) {
      if (!processOk(global.process)) {
        return function() {};
      }
      assert.equal(typeof cb, "function", "a callback must be provided for exit handler");
      if (loaded === false) {
        load();
      }
      var ev = "exit";
      if (opts && opts.alwaysLast) {
        ev = "afterexit";
      }
      var remove2 = function() {
        emitter.removeListener(ev, cb);
        if (emitter.listeners("exit").length === 0 && emitter.listeners("afterexit").length === 0) {
          unload();
        }
      };
      emitter.on(ev, cb);
      return remove2;
    };
    unload = function unload2() {
      if (!loaded || !processOk(global.process)) {
        return;
      }
      loaded = false;
      signals.forEach(function(sig) {
        try {
          process3.removeListener(sig, sigListeners[sig]);
        } catch (er) {}
      });
      process3.emit = originalProcessEmit;
      process3.reallyExit = originalProcessReallyExit;
      emitter.count -= 1;
    };
    module.exports.unload = unload;
    emit = function emit2(event, code, signal) {
      if (emitter.emitted[event]) {
        return;
      }
      emitter.emitted[event] = true;
      emitter.emit(event, code, signal);
    };
    sigListeners = {};
    signals.forEach(function(sig) {
      sigListeners[sig] = function listener() {
        if (!processOk(global.process)) {
          return;
        }
        var listeners = process3.listeners(sig);
        if (listeners.length === emitter.count) {
          unload();
          emit("exit", null, sig);
          emit("afterexit", null, sig);
          if (isWin && sig === "SIGHUP") {
            sig = "SIGINT";
          }
          process3.kill(process3.pid, sig);
        }
      };
    });
    module.exports.signals = function() {
      return signals;
    };
    loaded = false;
    load = function load2() {
      if (loaded || !processOk(global.process)) {
        return;
      }
      loaded = true;
      emitter.count += 1;
      signals = signals.filter(function(sig) {
        try {
          process3.on(sig, sigListeners[sig]);
          return true;
        } catch (er) {
          return false;
        }
      });
      process3.emit = processEmit;
      process3.reallyExit = processReallyExit;
    };
    module.exports.load = load;
    originalProcessReallyExit = process3.reallyExit;
    processReallyExit = function processReallyExit2(code) {
      if (!processOk(global.process)) {
        return;
      }
      process3.exitCode = code || 0;
      emit("exit", process3.exitCode, null);
      emit("afterexit", process3.exitCode, null);
      originalProcessReallyExit.call(process3, process3.exitCode);
    };
    originalProcessEmit = process3.emit;
    processEmit = function processEmit2(ev, arg) {
      if (ev === "exit" && processOk(global.process)) {
        if (arg !== undefined) {
          process3.exitCode = arg;
        }
        var ret = originalProcessEmit.apply(this, arguments);
        emit("exit", process3.exitCode, null);
        emit("afterexit", process3.exitCode, null);
        return ret;
      } else {
        return originalProcessEmit.apply(this, arguments);
      }
    };
  }
  var assert;
  var signals;
  var isWin;
  var EE;
  var emitter;
  var unload;
  var emit;
  var sigListeners;
  var loaded;
  var load;
  var originalProcessReallyExit;
  var processReallyExit;
  var originalProcessEmit;
  var processEmit;
});

// node_modules/scheduler/cjs/scheduler.production.min.js
var require_scheduler_production_min = __commonJS((exports) => {
  function f(a, b) {
    var c = a.length;
    a.push(b);
    a:
      for (;0 < c; ) {
        var d = c - 1 >>> 1, e = a[d];
        if (0 < g(e, b))
          a[d] = b, a[c] = e, c = d;
        else
          break a;
      }
  }
  function h(a) {
    return a.length === 0 ? null : a[0];
  }
  function k(a) {
    if (a.length === 0)
      return null;
    var b = a[0], c = a.pop();
    if (c !== b) {
      a[0] = c;
      a:
        for (var d = 0, e = a.length, w = e >>> 1;d < w; ) {
          var m = 2 * (d + 1) - 1, C = a[m], n = m + 1, x = a[n];
          if (0 > g(C, c))
            n < e && 0 > g(x, C) ? (a[d] = x, a[n] = c, d = n) : (a[d] = C, a[m] = c, d = m);
          else if (n < e && 0 > g(x, c))
            a[d] = x, a[n] = c, d = n;
          else
            break a;
        }
    }
    return b;
  }
  function g(a, b) {
    var c = a.sortIndex - b.sortIndex;
    return c !== 0 ? c : a.id - b.id;
  }
  if (typeof performance === "object" && typeof performance.now === "function") {
    l = performance;
    exports.unstable_now = function() {
      return l.now();
    };
  } else {
    p = Date, q = p.now();
    exports.unstable_now = function() {
      return p.now() - q;
    };
  }
  var l;
  var p;
  var q;
  var r = [];
  var t = [];
  var u = 1;
  var v = null;
  var y = 3;
  var z = false;
  var A = false;
  var B = false;
  var D = typeof setTimeout === "function" ? setTimeout : null;
  var E = typeof clearTimeout === "function" ? clearTimeout : null;
  var F = typeof setImmediate !== "undefined" ? setImmediate : null;
  typeof navigator !== "undefined" && navigator.scheduling !== undefined && navigator.scheduling.isInputPending !== undefined && navigator.scheduling.isInputPending.bind(navigator.scheduling);
  function G(a) {
    for (var b = h(t);b !== null; ) {
      if (b.callback === null)
        k(t);
      else if (b.startTime <= a)
        k(t), b.sortIndex = b.expirationTime, f(r, b);
      else
        break;
      b = h(t);
    }
  }
  function H(a) {
    B = false;
    G(a);
    if (!A)
      if (h(r) !== null)
        A = true, I(J);
      else {
        var b = h(t);
        b !== null && K(H, b.startTime - a);
      }
  }
  function J(a, b) {
    A = false;
    B && (B = false, E(L), L = -1);
    z = true;
    var c = y;
    try {
      G(b);
      for (v = h(r);v !== null && (!(v.expirationTime > b) || a && !M()); ) {
        var d = v.callback;
        if (typeof d === "function") {
          v.callback = null;
          y = v.priorityLevel;
          var e = d(v.expirationTime <= b);
          b = exports.unstable_now();
          typeof e === "function" ? v.callback = e : v === h(r) && k(r);
          G(b);
        } else
          k(r);
        v = h(r);
      }
      if (v !== null)
        var w = true;
      else {
        var m = h(t);
        m !== null && K(H, m.startTime - b);
        w = false;
      }
      return w;
    } finally {
      v = null, y = c, z = false;
    }
  }
  var N = false;
  var O = null;
  var L = -1;
  var P = 5;
  var Q = -1;
  function M() {
    return exports.unstable_now() - Q < P ? false : true;
  }
  function R() {
    if (O !== null) {
      var a = exports.unstable_now();
      Q = a;
      var b = true;
      try {
        b = O(true, a);
      } finally {
        b ? S() : (N = false, O = null);
      }
    } else
      N = false;
  }
  var S;
  if (typeof F === "function")
    S = function() {
      F(R);
    };
  else if (typeof MessageChannel !== "undefined") {
    T = new MessageChannel, U = T.port2;
    T.port1.onmessage = R;
    S = function() {
      U.postMessage(null);
    };
  } else
    S = function() {
      D(R, 0);
    };
  var T;
  var U;
  function I(a) {
    O = a;
    N || (N = true, S());
  }
  function K(a, b) {
    L = D(function() {
      a(exports.unstable_now());
    }, b);
  }
  exports.unstable_IdlePriority = 5;
  exports.unstable_ImmediatePriority = 1;
  exports.unstable_LowPriority = 4;
  exports.unstable_NormalPriority = 3;
  exports.unstable_Profiling = null;
  exports.unstable_UserBlockingPriority = 2;
  exports.unstable_cancelCallback = function(a) {
    a.callback = null;
  };
  exports.unstable_continueExecution = function() {
    A || z || (A = true, I(J));
  };
  exports.unstable_forceFrameRate = function(a) {
    0 > a || 125 < a ? console.error("forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported") : P = 0 < a ? Math.floor(1000 / a) : 5;
  };
  exports.unstable_getCurrentPriorityLevel = function() {
    return y;
  };
  exports.unstable_getFirstCallbackNode = function() {
    return h(r);
  };
  exports.unstable_next = function(a) {
    switch (y) {
      case 1:
      case 2:
      case 3:
        var b = 3;
        break;
      default:
        b = y;
    }
    var c = y;
    y = b;
    try {
      return a();
    } finally {
      y = c;
    }
  };
  exports.unstable_pauseExecution = function() {};
  exports.unstable_requestPaint = function() {};
  exports.unstable_runWithPriority = function(a, b) {
    switch (a) {
      case 1:
      case 2:
      case 3:
      case 4:
      case 5:
        break;
      default:
        a = 3;
    }
    var c = y;
    y = a;
    try {
      return b();
    } finally {
      y = c;
    }
  };
  exports.unstable_scheduleCallback = function(a, b, c) {
    var d = exports.unstable_now();
    typeof c === "object" && c !== null ? (c = c.delay, c = typeof c === "number" && 0 < c ? d + c : d) : c = d;
    switch (a) {
      case 1:
        var e = -1;
        break;
      case 2:
        e = 250;
        break;
      case 5:
        e = 1073741823;
        break;
      case 4:
        e = 1e4;
        break;
      default:
        e = 5000;
    }
    e = c + e;
    a = { id: u++, callback: b, priorityLevel: a, startTime: c, expirationTime: e, sortIndex: -1 };
    c > d ? (a.sortIndex = c, f(t, a), h(r) === null && a === h(t) && (B ? (E(L), L = -1) : B = true, K(H, c - d))) : (a.sortIndex = e, f(r, a), A || z || (A = true, I(J)));
    return a;
  };
  exports.unstable_shouldYield = M;
  exports.unstable_wrapCallback = function(a) {
    var b = y;
    return function() {
      var c = y;
      y = b;
      try {
        return a.apply(this, arguments);
      } finally {
        y = c;
      }
    };
  };
});

// node_modules/scheduler/index.js
var require_scheduler = __commonJS((exports, module) => {
  if (true) {
    module.exports = require_scheduler_production_min();
  } else {}
});

// node_modules/react-reconciler/cjs/react-reconciler.production.min.js
var require_react_reconciler_production_min = __commonJS((exports, module) => {
  var aa = __toESM(require_react());
  var ba = __toESM(require_scheduler());
  module.exports = function $$$reconciler($$$hostConfig) {
    var exports2 = {};
    var ca = Object.assign;
    function n(a) {
      for (var b = "https://reactjs.org/docs/error-decoder.html?invariant=" + a, c = 1;c < arguments.length; c++)
        b += "&args[]=" + encodeURIComponent(arguments[c]);
      return "Minified React error #" + a + "; visit " + b + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
    }
    var da = aa.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED, ea = Symbol.for("react.element"), fa = Symbol.for("react.portal"), ha = Symbol.for("react.fragment"), ia = Symbol.for("react.strict_mode"), ja = Symbol.for("react.profiler"), ka = Symbol.for("react.provider"), la = Symbol.for("react.context"), ma = Symbol.for("react.forward_ref"), na = Symbol.for("react.suspense"), oa = Symbol.for("react.suspense_list"), pa = Symbol.for("react.memo"), qa = Symbol.for("react.lazy");
    Symbol.for("react.scope");
    Symbol.for("react.debug_trace_mode");
    var ra = Symbol.for("react.offscreen");
    Symbol.for("react.legacy_hidden");
    Symbol.for("react.cache");
    Symbol.for("react.tracing_marker");
    var sa = Symbol.iterator;
    function ta(a) {
      if (a === null || typeof a !== "object")
        return null;
      a = sa && a[sa] || a["@@iterator"];
      return typeof a === "function" ? a : null;
    }
    function ua(a) {
      if (a == null)
        return null;
      if (typeof a === "function")
        return a.displayName || a.name || null;
      if (typeof a === "string")
        return a;
      switch (a) {
        case ha:
          return "Fragment";
        case fa:
          return "Portal";
        case ja:
          return "Profiler";
        case ia:
          return "StrictMode";
        case na:
          return "Suspense";
        case oa:
          return "SuspenseList";
      }
      if (typeof a === "object")
        switch (a.$$typeof) {
          case la:
            return (a.displayName || "Context") + ".Consumer";
          case ka:
            return (a._context.displayName || "Context") + ".Provider";
          case ma:
            var b = a.render;
            a = a.displayName;
            a || (a = b.displayName || b.name || "", a = a !== "" ? "ForwardRef(" + a + ")" : "ForwardRef");
            return a;
          case pa:
            return b = a.displayName || null, b !== null ? b : ua(a.type) || "Memo";
          case qa:
            b = a._payload;
            a = a._init;
            try {
              return ua(a(b));
            } catch (c) {}
        }
      return null;
    }
    function va(a) {
      var b = a.type;
      switch (a.tag) {
        case 24:
          return "Cache";
        case 9:
          return (b.displayName || "Context") + ".Consumer";
        case 10:
          return (b._context.displayName || "Context") + ".Provider";
        case 18:
          return "DehydratedFragment";
        case 11:
          return a = b.render, a = a.displayName || a.name || "", b.displayName || (a !== "" ? "ForwardRef(" + a + ")" : "ForwardRef");
        case 7:
          return "Fragment";
        case 5:
          return b;
        case 4:
          return "Portal";
        case 3:
          return "Root";
        case 6:
          return "Text";
        case 16:
          return ua(b);
        case 8:
          return b === ia ? "StrictMode" : "Mode";
        case 22:
          return "Offscreen";
        case 12:
          return "Profiler";
        case 21:
          return "Scope";
        case 13:
          return "Suspense";
        case 19:
          return "SuspenseList";
        case 25:
          return "TracingMarker";
        case 1:
        case 0:
        case 17:
        case 2:
        case 14:
        case 15:
          if (typeof b === "function")
            return b.displayName || b.name || null;
          if (typeof b === "string")
            return b;
      }
      return null;
    }
    function wa(a) {
      var b = a, c = a;
      if (a.alternate)
        for (;b.return; )
          b = b.return;
      else {
        a = b;
        do
          b = a, (b.flags & 4098) !== 0 && (c = b.return), a = b.return;
        while (a);
      }
      return b.tag === 3 ? c : null;
    }
    function xa(a) {
      if (wa(a) !== a)
        throw Error(n(188));
    }
    function za(a) {
      var b = a.alternate;
      if (!b) {
        b = wa(a);
        if (b === null)
          throw Error(n(188));
        return b !== a ? null : a;
      }
      for (var c = a, d = b;; ) {
        var e = c.return;
        if (e === null)
          break;
        var f = e.alternate;
        if (f === null) {
          d = e.return;
          if (d !== null) {
            c = d;
            continue;
          }
          break;
        }
        if (e.child === f.child) {
          for (f = e.child;f; ) {
            if (f === c)
              return xa(e), a;
            if (f === d)
              return xa(e), b;
            f = f.sibling;
          }
          throw Error(n(188));
        }
        if (c.return !== d.return)
          c = e, d = f;
        else {
          for (var g = false, h = e.child;h; ) {
            if (h === c) {
              g = true;
              c = e;
              d = f;
              break;
            }
            if (h === d) {
              g = true;
              d = e;
              c = f;
              break;
            }
            h = h.sibling;
          }
          if (!g) {
            for (h = f.child;h; ) {
              if (h === c) {
                g = true;
                c = f;
                d = e;
                break;
              }
              if (h === d) {
                g = true;
                d = f;
                c = e;
                break;
              }
              h = h.sibling;
            }
            if (!g)
              throw Error(n(189));
          }
        }
        if (c.alternate !== d)
          throw Error(n(190));
      }
      if (c.tag !== 3)
        throw Error(n(188));
      return c.stateNode.current === c ? a : b;
    }
    function Aa(a) {
      a = za(a);
      return a !== null ? Ba(a) : null;
    }
    function Ba(a) {
      if (a.tag === 5 || a.tag === 6)
        return a;
      for (a = a.child;a !== null; ) {
        var b = Ba(a);
        if (b !== null)
          return b;
        a = a.sibling;
      }
      return null;
    }
    function Ca(a) {
      if (a.tag === 5 || a.tag === 6)
        return a;
      for (a = a.child;a !== null; ) {
        if (a.tag !== 4) {
          var b = Ca(a);
          if (b !== null)
            return b;
        }
        a = a.sibling;
      }
      return null;
    }
    var Da = Array.isArray, Ea = $$$hostConfig.getPublicInstance, Fa = $$$hostConfig.getRootHostContext, Ga = $$$hostConfig.getChildHostContext, Ha = $$$hostConfig.prepareForCommit, Ia = $$$hostConfig.resetAfterCommit, Ja = $$$hostConfig.createInstance, Ka = $$$hostConfig.appendInitialChild, La = $$$hostConfig.finalizeInitialChildren, Ma = $$$hostConfig.prepareUpdate, Na = $$$hostConfig.shouldSetTextContent, Oa = $$$hostConfig.createTextInstance, Pa = $$$hostConfig.scheduleTimeout, Qa = $$$hostConfig.cancelTimeout, Ra = $$$hostConfig.noTimeout, Sa = $$$hostConfig.isPrimaryRenderer, Ta = $$$hostConfig.supportsMutation, Ua = $$$hostConfig.supportsPersistence, Va = $$$hostConfig.supportsHydration, Wa = $$$hostConfig.getInstanceFromNode, Xa = $$$hostConfig.preparePortalMount, Ya = $$$hostConfig.getCurrentEventPriority, Za = $$$hostConfig.detachDeletedInstance, $a = $$$hostConfig.supportsMicrotasks, ab = $$$hostConfig.scheduleMicrotask, bb = $$$hostConfig.supportsTestSelectors, cb = $$$hostConfig.findFiberRoot, db = $$$hostConfig.getBoundingRect, eb = $$$hostConfig.getTextContent, fb = $$$hostConfig.isHiddenSubtree, gb = $$$hostConfig.matchAccessibilityRole, hb = $$$hostConfig.setFocusIfFocusable, ib = $$$hostConfig.setupIntersectionObserver, jb = $$$hostConfig.appendChild, kb = $$$hostConfig.appendChildToContainer, lb = $$$hostConfig.commitTextUpdate, mb = $$$hostConfig.commitMount, nb = $$$hostConfig.commitUpdate, ob = $$$hostConfig.insertBefore, pb = $$$hostConfig.insertInContainerBefore, qb = $$$hostConfig.removeChild, rb = $$$hostConfig.removeChildFromContainer, sb = $$$hostConfig.resetTextContent, tb = $$$hostConfig.hideInstance, ub = $$$hostConfig.hideTextInstance, vb = $$$hostConfig.unhideInstance, wb = $$$hostConfig.unhideTextInstance, xb = $$$hostConfig.clearContainer, yb = $$$hostConfig.cloneInstance, zb = $$$hostConfig.createContainerChildSet, Ab = $$$hostConfig.appendChildToContainerChildSet, Bb = $$$hostConfig.finalizeContainerChildren, Cb = $$$hostConfig.replaceContainerChildren, Eb = $$$hostConfig.cloneHiddenInstance, Fb = $$$hostConfig.cloneHiddenTextInstance, Gb = $$$hostConfig.canHydrateInstance, Hb = $$$hostConfig.canHydrateTextInstance, Ib = $$$hostConfig.canHydrateSuspenseInstance, Jb = $$$hostConfig.isSuspenseInstancePending, Kb = $$$hostConfig.isSuspenseInstanceFallback, Lb = $$$hostConfig.getSuspenseInstanceFallbackErrorDetails, Mb = $$$hostConfig.registerSuspenseInstanceRetry, Nb = $$$hostConfig.getNextHydratableSibling, Ob = $$$hostConfig.getFirstHydratableChild, Pb = $$$hostConfig.getFirstHydratableChildWithinContainer, Qb = $$$hostConfig.getFirstHydratableChildWithinSuspenseInstance, Rb = $$$hostConfig.hydrateInstance, Sb = $$$hostConfig.hydrateTextInstance, Tb = $$$hostConfig.hydrateSuspenseInstance, Ub = $$$hostConfig.getNextHydratableInstanceAfterSuspenseInstance, Vb = $$$hostConfig.commitHydratedContainer, Wb = $$$hostConfig.commitHydratedSuspenseInstance, Xb = $$$hostConfig.clearSuspenseBoundary, Yb = $$$hostConfig.clearSuspenseBoundaryFromContainer, Zb = $$$hostConfig.shouldDeleteUnhydratedTailInstances, $b = $$$hostConfig.didNotMatchHydratedContainerTextInstance, ac = $$$hostConfig.didNotMatchHydratedTextInstance, bc;
    function cc(a) {
      if (bc === undefined)
        try {
          throw Error();
        } catch (c) {
          var b = c.stack.trim().match(/\n( *(at )?)/);
          bc = b && b[1] || "";
        }
      return `
` + bc + a;
    }
    var dc = false;
    function ec(a, b) {
      if (!a || dc)
        return "";
      dc = true;
      var c = Error.prepareStackTrace;
      Error.prepareStackTrace = undefined;
      try {
        if (b)
          if (b = function() {
            throw Error();
          }, Object.defineProperty(b.prototype, "props", { set: function() {
            throw Error();
          } }), typeof Reflect === "object" && Reflect.construct) {
            try {
              Reflect.construct(b, []);
            } catch (l) {
              var d = l;
            }
            Reflect.construct(a, [], b);
          } else {
            try {
              b.call();
            } catch (l) {
              d = l;
            }
            a.call(b.prototype);
          }
        else {
          try {
            throw Error();
          } catch (l) {
            d = l;
          }
          a();
        }
      } catch (l) {
        if (l && d && typeof l.stack === "string") {
          for (var e = l.stack.split(`
`), f = d.stack.split(`
`), g = e.length - 1, h = f.length - 1;1 <= g && 0 <= h && e[g] !== f[h]; )
            h--;
          for (;1 <= g && 0 <= h; g--, h--)
            if (e[g] !== f[h]) {
              if (g !== 1 || h !== 1) {
                do
                  if (g--, h--, 0 > h || e[g] !== f[h]) {
                    var k = `
` + e[g].replace(" at new ", " at ");
                    a.displayName && k.includes("<anonymous>") && (k = k.replace("<anonymous>", a.displayName));
                    return k;
                  }
                while (1 <= g && 0 <= h);
              }
              break;
            }
        }
      } finally {
        dc = false, Error.prepareStackTrace = c;
      }
      return (a = a ? a.displayName || a.name : "") ? cc(a) : "";
    }
    var fc = Object.prototype.hasOwnProperty, gc = [], hc = -1;
    function ic(a) {
      return { current: a };
    }
    function q(a) {
      0 > hc || (a.current = gc[hc], gc[hc] = null, hc--);
    }
    function v(a, b) {
      hc++;
      gc[hc] = a.current;
      a.current = b;
    }
    var jc = {}, x = ic(jc), z = ic(false), kc = jc;
    function mc(a, b) {
      var c = a.type.contextTypes;
      if (!c)
        return jc;
      var d = a.stateNode;
      if (d && d.__reactInternalMemoizedUnmaskedChildContext === b)
        return d.__reactInternalMemoizedMaskedChildContext;
      var e = {}, f;
      for (f in c)
        e[f] = b[f];
      d && (a = a.stateNode, a.__reactInternalMemoizedUnmaskedChildContext = b, a.__reactInternalMemoizedMaskedChildContext = e);
      return e;
    }
    function A(a) {
      a = a.childContextTypes;
      return a !== null && a !== undefined;
    }
    function nc() {
      q(z);
      q(x);
    }
    function oc(a, b, c) {
      if (x.current !== jc)
        throw Error(n(168));
      v(x, b);
      v(z, c);
    }
    function pc(a, b, c) {
      var d = a.stateNode;
      b = b.childContextTypes;
      if (typeof d.getChildContext !== "function")
        return c;
      d = d.getChildContext();
      for (var e in d)
        if (!(e in b))
          throw Error(n(108, va(a) || "Unknown", e));
      return ca({}, c, d);
    }
    function qc(a) {
      a = (a = a.stateNode) && a.__reactInternalMemoizedMergedChildContext || jc;
      kc = x.current;
      v(x, a);
      v(z, z.current);
      return true;
    }
    function rc(a, b, c) {
      var d = a.stateNode;
      if (!d)
        throw Error(n(169));
      c ? (a = pc(a, b, kc), d.__reactInternalMemoizedMergedChildContext = a, q(z), q(x), v(x, a)) : q(z);
      v(z, c);
    }
    var tc = Math.clz32 ? Math.clz32 : sc, uc = Math.log, vc = Math.LN2;
    function sc(a) {
      a >>>= 0;
      return a === 0 ? 32 : 31 - (uc(a) / vc | 0) | 0;
    }
    var wc = 64, xc = 4194304;
    function yc(a) {
      switch (a & -a) {
        case 1:
          return 1;
        case 2:
          return 2;
        case 4:
          return 4;
        case 8:
          return 8;
        case 16:
          return 16;
        case 32:
          return 32;
        case 64:
        case 128:
        case 256:
        case 512:
        case 1024:
        case 2048:
        case 4096:
        case 8192:
        case 16384:
        case 32768:
        case 65536:
        case 131072:
        case 262144:
        case 524288:
        case 1048576:
        case 2097152:
          return a & 4194240;
        case 4194304:
        case 8388608:
        case 16777216:
        case 33554432:
        case 67108864:
          return a & 130023424;
        case 134217728:
          return 134217728;
        case 268435456:
          return 268435456;
        case 536870912:
          return 536870912;
        case 1073741824:
          return 1073741824;
        default:
          return a;
      }
    }
    function zc(a, b) {
      var c = a.pendingLanes;
      if (c === 0)
        return 0;
      var d = 0, e = a.suspendedLanes, f = a.pingedLanes, g = c & 268435455;
      if (g !== 0) {
        var h = g & ~e;
        h !== 0 ? d = yc(h) : (f &= g, f !== 0 && (d = yc(f)));
      } else
        g = c & ~e, g !== 0 ? d = yc(g) : f !== 0 && (d = yc(f));
      if (d === 0)
        return 0;
      if (b !== 0 && b !== d && (b & e) === 0 && (e = d & -d, f = b & -b, e >= f || e === 16 && (f & 4194240) !== 0))
        return b;
      (d & 4) !== 0 && (d |= c & 16);
      b = a.entangledLanes;
      if (b !== 0)
        for (a = a.entanglements, b &= d;0 < b; )
          c = 31 - tc(b), e = 1 << c, d |= a[c], b &= ~e;
      return d;
    }
    function Ac(a, b) {
      switch (a) {
        case 1:
        case 2:
        case 4:
          return b + 250;
        case 8:
        case 16:
        case 32:
        case 64:
        case 128:
        case 256:
        case 512:
        case 1024:
        case 2048:
        case 4096:
        case 8192:
        case 16384:
        case 32768:
        case 65536:
        case 131072:
        case 262144:
        case 524288:
        case 1048576:
        case 2097152:
          return b + 5000;
        case 4194304:
        case 8388608:
        case 16777216:
        case 33554432:
        case 67108864:
          return -1;
        case 134217728:
        case 268435456:
        case 536870912:
        case 1073741824:
          return -1;
        default:
          return -1;
      }
    }
    function Bc(a, b) {
      for (var { suspendedLanes: c, pingedLanes: d, expirationTimes: e, pendingLanes: f } = a;0 < f; ) {
        var g = 31 - tc(f), h = 1 << g, k = e[g];
        if (k === -1) {
          if ((h & c) === 0 || (h & d) !== 0)
            e[g] = Ac(h, b);
        } else
          k <= b && (a.expiredLanes |= h);
        f &= ~h;
      }
    }
    function Cc(a) {
      a = a.pendingLanes & -1073741825;
      return a !== 0 ? a : a & 1073741824 ? 1073741824 : 0;
    }
    function Dc() {
      var a = wc;
      wc <<= 1;
      (wc & 4194240) === 0 && (wc = 64);
      return a;
    }
    function Ec(a) {
      for (var b = [], c = 0;31 > c; c++)
        b.push(a);
      return b;
    }
    function Fc(a, b, c) {
      a.pendingLanes |= b;
      b !== 536870912 && (a.suspendedLanes = 0, a.pingedLanes = 0);
      a = a.eventTimes;
      b = 31 - tc(b);
      a[b] = c;
    }
    function Gc(a, b) {
      var c = a.pendingLanes & ~b;
      a.pendingLanes = b;
      a.suspendedLanes = 0;
      a.pingedLanes = 0;
      a.expiredLanes &= b;
      a.mutableReadLanes &= b;
      a.entangledLanes &= b;
      b = a.entanglements;
      var d = a.eventTimes;
      for (a = a.expirationTimes;0 < c; ) {
        var e = 31 - tc(c), f = 1 << e;
        b[e] = 0;
        d[e] = -1;
        a[e] = -1;
        c &= ~f;
      }
    }
    function Hc(a, b) {
      var c = a.entangledLanes |= b;
      for (a = a.entanglements;c; ) {
        var d = 31 - tc(c), e = 1 << d;
        e & b | a[d] & b && (a[d] |= b);
        c &= ~e;
      }
    }
    var C = 0;
    function Ic(a) {
      a &= -a;
      return 1 < a ? 4 < a ? (a & 268435455) !== 0 ? 16 : 536870912 : 4 : 1;
    }
    var Jc = ba.unstable_scheduleCallback, Kc = ba.unstable_cancelCallback, Lc = ba.unstable_shouldYield, Mc = ba.unstable_requestPaint, D = ba.unstable_now, Nc = ba.unstable_ImmediatePriority, Oc = ba.unstable_UserBlockingPriority, Pc = ba.unstable_NormalPriority, Qc = ba.unstable_IdlePriority, Rc = null, Sc = null;
    function Tc(a) {
      if (Sc && typeof Sc.onCommitFiberRoot === "function")
        try {
          Sc.onCommitFiberRoot(Rc, a, undefined, (a.current.flags & 128) === 128);
        } catch (b) {}
    }
    function Uc(a, b) {
      return a === b && (a !== 0 || 1 / a === 1 / b) || a !== a && b !== b;
    }
    var Vc = typeof Object.is === "function" ? Object.is : Uc, Wc = null, Xc = false, Yc = false;
    function Zc(a) {
      Wc === null ? Wc = [a] : Wc.push(a);
    }
    function $c(a) {
      Xc = true;
      Zc(a);
    }
    function ad() {
      if (!Yc && Wc !== null) {
        Yc = true;
        var a = 0, b = C;
        try {
          var c = Wc;
          for (C = 1;a < c.length; a++) {
            var d = c[a];
            do
              d = d(true);
            while (d !== null);
          }
          Wc = null;
          Xc = false;
        } catch (e) {
          throw Wc !== null && (Wc = Wc.slice(a + 1)), Jc(Nc, ad), e;
        } finally {
          C = b, Yc = false;
        }
      }
      return null;
    }
    var bd = [], cd = 0, dd = null, ed = 0, fd = [], gd = 0, hd = null, id = 1, jd = "";
    function kd(a, b) {
      bd[cd++] = ed;
      bd[cd++] = dd;
      dd = a;
      ed = b;
    }
    function ld(a, b, c) {
      fd[gd++] = id;
      fd[gd++] = jd;
      fd[gd++] = hd;
      hd = a;
      var d = id;
      a = jd;
      var e = 32 - tc(d) - 1;
      d &= ~(1 << e);
      c += 1;
      var f = 32 - tc(b) + e;
      if (30 < f) {
        var g = e - e % 5;
        f = (d & (1 << g) - 1).toString(32);
        d >>= g;
        e -= g;
        id = 1 << 32 - tc(b) + e | c << e | d;
        jd = f + a;
      } else
        id = 1 << f | c << e | d, jd = a;
    }
    function md(a) {
      a.return !== null && (kd(a, 1), ld(a, 1, 0));
    }
    function nd(a) {
      for (;a === dd; )
        dd = bd[--cd], bd[cd] = null, ed = bd[--cd], bd[cd] = null;
      for (;a === hd; )
        hd = fd[--gd], fd[gd] = null, jd = fd[--gd], fd[gd] = null, id = fd[--gd], fd[gd] = null;
    }
    var od = null, pd = null, F = false, qd = false, rd = null;
    function sd(a, b) {
      var c = td(5, null, null, 0);
      c.elementType = "DELETED";
      c.stateNode = b;
      c.return = a;
      b = a.deletions;
      b === null ? (a.deletions = [c], a.flags |= 16) : b.push(c);
    }
    function ud(a, b) {
      switch (a.tag) {
        case 5:
          return b = Gb(b, a.type, a.pendingProps), b !== null ? (a.stateNode = b, od = a, pd = Ob(b), true) : false;
        case 6:
          return b = Hb(b, a.pendingProps), b !== null ? (a.stateNode = b, od = a, pd = null, true) : false;
        case 13:
          b = Ib(b);
          if (b !== null) {
            var c = hd !== null ? { id, overflow: jd } : null;
            a.memoizedState = { dehydrated: b, treeContext: c, retryLane: 1073741824 };
            c = td(18, null, null, 0);
            c.stateNode = b;
            c.return = a;
            a.child = c;
            od = a;
            pd = null;
            return true;
          }
          return false;
        default:
          return false;
      }
    }
    function vd(a) {
      return (a.mode & 1) !== 0 && (a.flags & 128) === 0;
    }
    function wd(a) {
      if (F) {
        var b = pd;
        if (b) {
          var c = b;
          if (!ud(a, b)) {
            if (vd(a))
              throw Error(n(418));
            b = Nb(c);
            var d = od;
            b && ud(a, b) ? sd(d, c) : (a.flags = a.flags & -4097 | 2, F = false, od = a);
          }
        } else {
          if (vd(a))
            throw Error(n(418));
          a.flags = a.flags & -4097 | 2;
          F = false;
          od = a;
        }
      }
    }
    function xd(a) {
      for (a = a.return;a !== null && a.tag !== 5 && a.tag !== 3 && a.tag !== 13; )
        a = a.return;
      od = a;
    }
    function yd(a) {
      if (!Va || a !== od)
        return false;
      if (!F)
        return xd(a), F = true, false;
      if (a.tag !== 3 && (a.tag !== 5 || Zb(a.type) && !Na(a.type, a.memoizedProps))) {
        var b = pd;
        if (b) {
          if (vd(a))
            throw zd(), Error(n(418));
          for (;b; )
            sd(a, b), b = Nb(b);
        }
      }
      xd(a);
      if (a.tag === 13) {
        if (!Va)
          throw Error(n(316));
        a = a.memoizedState;
        a = a !== null ? a.dehydrated : null;
        if (!a)
          throw Error(n(317));
        pd = Ub(a);
      } else
        pd = od ? Nb(a.stateNode) : null;
      return true;
    }
    function zd() {
      for (var a = pd;a; )
        a = Nb(a);
    }
    function Ad() {
      Va && (pd = od = null, qd = F = false);
    }
    function Bd(a) {
      rd === null ? rd = [a] : rd.push(a);
    }
    var Cd = da.ReactCurrentBatchConfig;
    function Dd(a, b) {
      if (Vc(a, b))
        return true;
      if (typeof a !== "object" || a === null || typeof b !== "object" || b === null)
        return false;
      var c = Object.keys(a), d = Object.keys(b);
      if (c.length !== d.length)
        return false;
      for (d = 0;d < c.length; d++) {
        var e = c[d];
        if (!fc.call(b, e) || !Vc(a[e], b[e]))
          return false;
      }
      return true;
    }
    function Ed(a) {
      switch (a.tag) {
        case 5:
          return cc(a.type);
        case 16:
          return cc("Lazy");
        case 13:
          return cc("Suspense");
        case 19:
          return cc("SuspenseList");
        case 0:
        case 2:
        case 15:
          return a = ec(a.type, false), a;
        case 11:
          return a = ec(a.type.render, false), a;
        case 1:
          return a = ec(a.type, true), a;
        default:
          return "";
      }
    }
    function Fd(a, b, c) {
      a = c.ref;
      if (a !== null && typeof a !== "function" && typeof a !== "object") {
        if (c._owner) {
          c = c._owner;
          if (c) {
            if (c.tag !== 1)
              throw Error(n(309));
            var d = c.stateNode;
          }
          if (!d)
            throw Error(n(147, a));
          var e = d, f = "" + a;
          if (b !== null && b.ref !== null && typeof b.ref === "function" && b.ref._stringRef === f)
            return b.ref;
          b = function(a2) {
            var b2 = e.refs;
            a2 === null ? delete b2[f] : b2[f] = a2;
          };
          b._stringRef = f;
          return b;
        }
        if (typeof a !== "string")
          throw Error(n(284));
        if (!c._owner)
          throw Error(n(290, a));
      }
      return a;
    }
    function Gd(a, b) {
      a = Object.prototype.toString.call(b);
      throw Error(n(31, a === "[object Object]" ? "object with keys {" + Object.keys(b).join(", ") + "}" : a));
    }
    function Hd(a) {
      var b = a._init;
      return b(a._payload);
    }
    function Id(a) {
      function b(b2, c2) {
        if (a) {
          var d2 = b2.deletions;
          d2 === null ? (b2.deletions = [c2], b2.flags |= 16) : d2.push(c2);
        }
      }
      function c(c2, d2) {
        if (!a)
          return null;
        for (;d2 !== null; )
          b(c2, d2), d2 = d2.sibling;
        return null;
      }
      function d(a2, b2) {
        for (a2 = new Map;b2 !== null; )
          b2.key !== null ? a2.set(b2.key, b2) : a2.set(b2.index, b2), b2 = b2.sibling;
        return a2;
      }
      function e(a2, b2) {
        a2 = Jd(a2, b2);
        a2.index = 0;
        a2.sibling = null;
        return a2;
      }
      function f(b2, c2, d2) {
        b2.index = d2;
        if (!a)
          return b2.flags |= 1048576, c2;
        d2 = b2.alternate;
        if (d2 !== null)
          return d2 = d2.index, d2 < c2 ? (b2.flags |= 2, c2) : d2;
        b2.flags |= 2;
        return c2;
      }
      function g(b2) {
        a && b2.alternate === null && (b2.flags |= 2);
        return b2;
      }
      function h(a2, b2, c2, d2) {
        if (b2 === null || b2.tag !== 6)
          return b2 = Kd(c2, a2.mode, d2), b2.return = a2, b2;
        b2 = e(b2, c2);
        b2.return = a2;
        return b2;
      }
      function k(a2, b2, c2, d2) {
        var f2 = c2.type;
        if (f2 === ha)
          return m(a2, b2, c2.props.children, d2, c2.key);
        if (b2 !== null && (b2.elementType === f2 || typeof f2 === "object" && f2 !== null && f2.$$typeof === qa && Hd(f2) === b2.type))
          return d2 = e(b2, c2.props), d2.ref = Fd(a2, b2, c2), d2.return = a2, d2;
        d2 = Ld(c2.type, c2.key, c2.props, null, a2.mode, d2);
        d2.ref = Fd(a2, b2, c2);
        d2.return = a2;
        return d2;
      }
      function l(a2, b2, c2, d2) {
        if (b2 === null || b2.tag !== 4 || b2.stateNode.containerInfo !== c2.containerInfo || b2.stateNode.implementation !== c2.implementation)
          return b2 = Md(c2, a2.mode, d2), b2.return = a2, b2;
        b2 = e(b2, c2.children || []);
        b2.return = a2;
        return b2;
      }
      function m(a2, b2, c2, d2, f2) {
        if (b2 === null || b2.tag !== 7)
          return b2 = Nd(c2, a2.mode, d2, f2), b2.return = a2, b2;
        b2 = e(b2, c2);
        b2.return = a2;
        return b2;
      }
      function r(a2, b2, c2) {
        if (typeof b2 === "string" && b2 !== "" || typeof b2 === "number")
          return b2 = Kd("" + b2, a2.mode, c2), b2.return = a2, b2;
        if (typeof b2 === "object" && b2 !== null) {
          switch (b2.$$typeof) {
            case ea:
              return c2 = Ld(b2.type, b2.key, b2.props, null, a2.mode, c2), c2.ref = Fd(a2, null, b2), c2.return = a2, c2;
            case fa:
              return b2 = Md(b2, a2.mode, c2), b2.return = a2, b2;
            case qa:
              var d2 = b2._init;
              return r(a2, d2(b2._payload), c2);
          }
          if (Da(b2) || ta(b2))
            return b2 = Nd(b2, a2.mode, c2, null), b2.return = a2, b2;
          Gd(a2, b2);
        }
        return null;
      }
      function p(a2, b2, c2, d2) {
        var e2 = b2 !== null ? b2.key : null;
        if (typeof c2 === "string" && c2 !== "" || typeof c2 === "number")
          return e2 !== null ? null : h(a2, b2, "" + c2, d2);
        if (typeof c2 === "object" && c2 !== null) {
          switch (c2.$$typeof) {
            case ea:
              return c2.key === e2 ? k(a2, b2, c2, d2) : null;
            case fa:
              return c2.key === e2 ? l(a2, b2, c2, d2) : null;
            case qa:
              return e2 = c2._init, p(a2, b2, e2(c2._payload), d2);
          }
          if (Da(c2) || ta(c2))
            return e2 !== null ? null : m(a2, b2, c2, d2, null);
          Gd(a2, c2);
        }
        return null;
      }
      function B(a2, b2, c2, d2, e2) {
        if (typeof d2 === "string" && d2 !== "" || typeof d2 === "number")
          return a2 = a2.get(c2) || null, h(b2, a2, "" + d2, e2);
        if (typeof d2 === "object" && d2 !== null) {
          switch (d2.$$typeof) {
            case ea:
              return a2 = a2.get(d2.key === null ? c2 : d2.key) || null, k(b2, a2, d2, e2);
            case fa:
              return a2 = a2.get(d2.key === null ? c2 : d2.key) || null, l(b2, a2, d2, e2);
            case qa:
              var f2 = d2._init;
              return B(a2, b2, c2, f2(d2._payload), e2);
          }
          if (Da(d2) || ta(d2))
            return a2 = a2.get(c2) || null, m(b2, a2, d2, e2, null);
          Gd(b2, d2);
        }
        return null;
      }
      function w(e2, g2, h2, k2) {
        for (var l2 = null, m2 = null, u = g2, t = g2 = 0, E = null;u !== null && t < h2.length; t++) {
          u.index > t ? (E = u, u = null) : E = u.sibling;
          var y = p(e2, u, h2[t], k2);
          if (y === null) {
            u === null && (u = E);
            break;
          }
          a && u && y.alternate === null && b(e2, u);
          g2 = f(y, g2, t);
          m2 === null ? l2 = y : m2.sibling = y;
          m2 = y;
          u = E;
        }
        if (t === h2.length)
          return c(e2, u), F && kd(e2, t), l2;
        if (u === null) {
          for (;t < h2.length; t++)
            u = r(e2, h2[t], k2), u !== null && (g2 = f(u, g2, t), m2 === null ? l2 = u : m2.sibling = u, m2 = u);
          F && kd(e2, t);
          return l2;
        }
        for (u = d(e2, u);t < h2.length; t++)
          E = B(u, e2, t, h2[t], k2), E !== null && (a && E.alternate !== null && u.delete(E.key === null ? t : E.key), g2 = f(E, g2, t), m2 === null ? l2 = E : m2.sibling = E, m2 = E);
        a && u.forEach(function(a2) {
          return b(e2, a2);
        });
        F && kd(e2, t);
        return l2;
      }
      function Y(e2, g2, h2, k2) {
        var l2 = ta(h2);
        if (typeof l2 !== "function")
          throw Error(n(150));
        h2 = l2.call(h2);
        if (h2 == null)
          throw Error(n(151));
        for (var u = l2 = null, m2 = g2, t = g2 = 0, E = null, y = h2.next();m2 !== null && !y.done; t++, y = h2.next()) {
          m2.index > t ? (E = m2, m2 = null) : E = m2.sibling;
          var w2 = p(e2, m2, y.value, k2);
          if (w2 === null) {
            m2 === null && (m2 = E);
            break;
          }
          a && m2 && w2.alternate === null && b(e2, m2);
          g2 = f(w2, g2, t);
          u === null ? l2 = w2 : u.sibling = w2;
          u = w2;
          m2 = E;
        }
        if (y.done)
          return c(e2, m2), F && kd(e2, t), l2;
        if (m2 === null) {
          for (;!y.done; t++, y = h2.next())
            y = r(e2, y.value, k2), y !== null && (g2 = f(y, g2, t), u === null ? l2 = y : u.sibling = y, u = y);
          F && kd(e2, t);
          return l2;
        }
        for (m2 = d(e2, m2);!y.done; t++, y = h2.next())
          y = B(m2, e2, t, y.value, k2), y !== null && (a && y.alternate !== null && m2.delete(y.key === null ? t : y.key), g2 = f(y, g2, t), u === null ? l2 = y : u.sibling = y, u = y);
        a && m2.forEach(function(a2) {
          return b(e2, a2);
        });
        F && kd(e2, t);
        return l2;
      }
      function ya(a2, d2, f2, h2) {
        typeof f2 === "object" && f2 !== null && f2.type === ha && f2.key === null && (f2 = f2.props.children);
        if (typeof f2 === "object" && f2 !== null) {
          switch (f2.$$typeof) {
            case ea:
              a: {
                for (var k2 = f2.key, l2 = d2;l2 !== null; ) {
                  if (l2.key === k2) {
                    k2 = f2.type;
                    if (k2 === ha) {
                      if (l2.tag === 7) {
                        c(a2, l2.sibling);
                        d2 = e(l2, f2.props.children);
                        d2.return = a2;
                        a2 = d2;
                        break a;
                      }
                    } else if (l2.elementType === k2 || typeof k2 === "object" && k2 !== null && k2.$$typeof === qa && Hd(k2) === l2.type) {
                      c(a2, l2.sibling);
                      d2 = e(l2, f2.props);
                      d2.ref = Fd(a2, l2, f2);
                      d2.return = a2;
                      a2 = d2;
                      break a;
                    }
                    c(a2, l2);
                    break;
                  } else
                    b(a2, l2);
                  l2 = l2.sibling;
                }
                f2.type === ha ? (d2 = Nd(f2.props.children, a2.mode, h2, f2.key), d2.return = a2, a2 = d2) : (h2 = Ld(f2.type, f2.key, f2.props, null, a2.mode, h2), h2.ref = Fd(a2, d2, f2), h2.return = a2, a2 = h2);
              }
              return g(a2);
            case fa:
              a: {
                for (l2 = f2.key;d2 !== null; ) {
                  if (d2.key === l2)
                    if (d2.tag === 4 && d2.stateNode.containerInfo === f2.containerInfo && d2.stateNode.implementation === f2.implementation) {
                      c(a2, d2.sibling);
                      d2 = e(d2, f2.children || []);
                      d2.return = a2;
                      a2 = d2;
                      break a;
                    } else {
                      c(a2, d2);
                      break;
                    }
                  else
                    b(a2, d2);
                  d2 = d2.sibling;
                }
                d2 = Md(f2, a2.mode, h2);
                d2.return = a2;
                a2 = d2;
              }
              return g(a2);
            case qa:
              return l2 = f2._init, ya(a2, d2, l2(f2._payload), h2);
          }
          if (Da(f2))
            return w(a2, d2, f2, h2);
          if (ta(f2))
            return Y(a2, d2, f2, h2);
          Gd(a2, f2);
        }
        return typeof f2 === "string" && f2 !== "" || typeof f2 === "number" ? (f2 = "" + f2, d2 !== null && d2.tag === 6 ? (c(a2, d2.sibling), d2 = e(d2, f2), d2.return = a2, a2 = d2) : (c(a2, d2), d2 = Kd(f2, a2.mode, h2), d2.return = a2, a2 = d2), g(a2)) : c(a2, d2);
      }
      return ya;
    }
    var Od = Id(true), Pd = Id(false), Qd = ic(null), Rd = null, Sd = null, Td = null;
    function Ud() {
      Td = Sd = Rd = null;
    }
    function Vd(a, b, c) {
      Sa ? (v(Qd, b._currentValue), b._currentValue = c) : (v(Qd, b._currentValue2), b._currentValue2 = c);
    }
    function Wd(a) {
      var b = Qd.current;
      q(Qd);
      Sa ? a._currentValue = b : a._currentValue2 = b;
    }
    function Xd(a, b, c) {
      for (;a !== null; ) {
        var d = a.alternate;
        (a.childLanes & b) !== b ? (a.childLanes |= b, d !== null && (d.childLanes |= b)) : d !== null && (d.childLanes & b) !== b && (d.childLanes |= b);
        if (a === c)
          break;
        a = a.return;
      }
    }
    function Yd(a, b) {
      Rd = a;
      Td = Sd = null;
      a = a.dependencies;
      a !== null && a.firstContext !== null && ((a.lanes & b) !== 0 && (G = true), a.firstContext = null);
    }
    function Zd(a) {
      var b = Sa ? a._currentValue : a._currentValue2;
      if (Td !== a)
        if (a = { context: a, memoizedValue: b, next: null }, Sd === null) {
          if (Rd === null)
            throw Error(n(308));
          Sd = a;
          Rd.dependencies = { lanes: 0, firstContext: a };
        } else
          Sd = Sd.next = a;
      return b;
    }
    var $d = null;
    function ae(a) {
      $d === null ? $d = [a] : $d.push(a);
    }
    function be(a, b, c, d) {
      var e = b.interleaved;
      e === null ? (c.next = c, ae(b)) : (c.next = e.next, e.next = c);
      b.interleaved = c;
      return ce(a, d);
    }
    function ce(a, b) {
      a.lanes |= b;
      var c = a.alternate;
      c !== null && (c.lanes |= b);
      c = a;
      for (a = a.return;a !== null; )
        a.childLanes |= b, c = a.alternate, c !== null && (c.childLanes |= b), c = a, a = a.return;
      return c.tag === 3 ? c.stateNode : null;
    }
    var de = false;
    function ee(a) {
      a.updateQueue = { baseState: a.memoizedState, firstBaseUpdate: null, lastBaseUpdate: null, shared: { pending: null, interleaved: null, lanes: 0 }, effects: null };
    }
    function fe(a, b) {
      a = a.updateQueue;
      b.updateQueue === a && (b.updateQueue = { baseState: a.baseState, firstBaseUpdate: a.firstBaseUpdate, lastBaseUpdate: a.lastBaseUpdate, shared: a.shared, effects: a.effects });
    }
    function ge(a, b) {
      return { eventTime: a, lane: b, tag: 0, payload: null, callback: null, next: null };
    }
    function he(a, b, c) {
      var d = a.updateQueue;
      if (d === null)
        return null;
      d = d.shared;
      if ((H & 2) !== 0) {
        var e = d.pending;
        e === null ? b.next = b : (b.next = e.next, e.next = b);
        d.pending = b;
        return ce(a, c);
      }
      e = d.interleaved;
      e === null ? (b.next = b, ae(d)) : (b.next = e.next, e.next = b);
      d.interleaved = b;
      return ce(a, c);
    }
    function ie(a, b, c) {
      b = b.updateQueue;
      if (b !== null && (b = b.shared, (c & 4194240) !== 0)) {
        var d = b.lanes;
        d &= a.pendingLanes;
        c |= d;
        b.lanes = c;
        Hc(a, c);
      }
    }
    function je(a, b) {
      var { updateQueue: c, alternate: d } = a;
      if (d !== null && (d = d.updateQueue, c === d)) {
        var e = null, f = null;
        c = c.firstBaseUpdate;
        if (c !== null) {
          do {
            var g = { eventTime: c.eventTime, lane: c.lane, tag: c.tag, payload: c.payload, callback: c.callback, next: null };
            f === null ? e = f = g : f = f.next = g;
            c = c.next;
          } while (c !== null);
          f === null ? e = f = b : f = f.next = b;
        } else
          e = f = b;
        c = { baseState: d.baseState, firstBaseUpdate: e, lastBaseUpdate: f, shared: d.shared, effects: d.effects };
        a.updateQueue = c;
        return;
      }
      a = c.lastBaseUpdate;
      a === null ? c.firstBaseUpdate = b : a.next = b;
      c.lastBaseUpdate = b;
    }
    function ke(a, b, c, d) {
      var e = a.updateQueue;
      de = false;
      var { firstBaseUpdate: f, lastBaseUpdate: g } = e, h = e.shared.pending;
      if (h !== null) {
        e.shared.pending = null;
        var k = h, l = k.next;
        k.next = null;
        g === null ? f = l : g.next = l;
        g = k;
        var m = a.alternate;
        m !== null && (m = m.updateQueue, h = m.lastBaseUpdate, h !== g && (h === null ? m.firstBaseUpdate = l : h.next = l, m.lastBaseUpdate = k));
      }
      if (f !== null) {
        var r = e.baseState;
        g = 0;
        m = l = k = null;
        h = f;
        do {
          var { lane: p, eventTime: B } = h;
          if ((d & p) === p) {
            m !== null && (m = m.next = {
              eventTime: B,
              lane: 0,
              tag: h.tag,
              payload: h.payload,
              callback: h.callback,
              next: null
            });
            a: {
              var w = a, Y = h;
              p = b;
              B = c;
              switch (Y.tag) {
                case 1:
                  w = Y.payload;
                  if (typeof w === "function") {
                    r = w.call(B, r, p);
                    break a;
                  }
                  r = w;
                  break a;
                case 3:
                  w.flags = w.flags & -65537 | 128;
                case 0:
                  w = Y.payload;
                  p = typeof w === "function" ? w.call(B, r, p) : w;
                  if (p === null || p === undefined)
                    break a;
                  r = ca({}, r, p);
                  break a;
                case 2:
                  de = true;
              }
            }
            h.callback !== null && h.lane !== 0 && (a.flags |= 64, p = e.effects, p === null ? e.effects = [h] : p.push(h));
          } else
            B = { eventTime: B, lane: p, tag: h.tag, payload: h.payload, callback: h.callback, next: null }, m === null ? (l = m = B, k = r) : m = m.next = B, g |= p;
          h = h.next;
          if (h === null)
            if (h = e.shared.pending, h === null)
              break;
            else
              p = h, h = p.next, p.next = null, e.lastBaseUpdate = p, e.shared.pending = null;
        } while (1);
        m === null && (k = r);
        e.baseState = k;
        e.firstBaseUpdate = l;
        e.lastBaseUpdate = m;
        b = e.shared.interleaved;
        if (b !== null) {
          e = b;
          do
            g |= e.lane, e = e.next;
          while (e !== b);
        } else
          f === null && (e.shared.lanes = 0);
        le |= g;
        a.lanes = g;
        a.memoizedState = r;
      }
    }
    function me(a, b, c) {
      a = b.effects;
      b.effects = null;
      if (a !== null)
        for (b = 0;b < a.length; b++) {
          var d = a[b], e = d.callback;
          if (e !== null) {
            d.callback = null;
            d = c;
            if (typeof e !== "function")
              throw Error(n(191, e));
            e.call(d);
          }
        }
    }
    var ne = {}, oe = ic(ne), pe = ic(ne), qe = ic(ne);
    function re(a) {
      if (a === ne)
        throw Error(n(174));
      return a;
    }
    function se(a, b) {
      v(qe, b);
      v(pe, a);
      v(oe, ne);
      a = Fa(b);
      q(oe);
      v(oe, a);
    }
    function te() {
      q(oe);
      q(pe);
      q(qe);
    }
    function ue(a) {
      var b = re(qe.current), c = re(oe.current);
      b = Ga(c, a.type, b);
      c !== b && (v(pe, a), v(oe, b));
    }
    function ve(a) {
      pe.current === a && (q(oe), q(pe));
    }
    var I = ic(0);
    function we(a) {
      for (var b = a;b !== null; ) {
        if (b.tag === 13) {
          var c = b.memoizedState;
          if (c !== null && (c = c.dehydrated, c === null || Jb(c) || Kb(c)))
            return b;
        } else if (b.tag === 19 && b.memoizedProps.revealOrder !== undefined) {
          if ((b.flags & 128) !== 0)
            return b;
        } else if (b.child !== null) {
          b.child.return = b;
          b = b.child;
          continue;
        }
        if (b === a)
          break;
        for (;b.sibling === null; ) {
          if (b.return === null || b.return === a)
            return null;
          b = b.return;
        }
        b.sibling.return = b.return;
        b = b.sibling;
      }
      return null;
    }
    var xe = [];
    function ye() {
      for (var a = 0;a < xe.length; a++) {
        var b = xe[a];
        Sa ? b._workInProgressVersionPrimary = null : b._workInProgressVersionSecondary = null;
      }
      xe.length = 0;
    }
    var { ReactCurrentDispatcher: ze, ReactCurrentBatchConfig: Ae } = da, Be = 0, J = null, K = null, L = null, Ce = false, De = false, Ee = 0, Fe = 0;
    function M() {
      throw Error(n(321));
    }
    function Ge(a, b) {
      if (b === null)
        return false;
      for (var c = 0;c < b.length && c < a.length; c++)
        if (!Vc(a[c], b[c]))
          return false;
      return true;
    }
    function He(a, b, c, d, e, f) {
      Be = f;
      J = b;
      b.memoizedState = null;
      b.updateQueue = null;
      b.lanes = 0;
      ze.current = a === null || a.memoizedState === null ? Ie : Je;
      a = c(d, e);
      if (De) {
        f = 0;
        do {
          De = false;
          Ee = 0;
          if (25 <= f)
            throw Error(n(301));
          f += 1;
          L = K = null;
          b.updateQueue = null;
          ze.current = Ke;
          a = c(d, e);
        } while (De);
      }
      ze.current = Le;
      b = K !== null && K.next !== null;
      Be = 0;
      L = K = J = null;
      Ce = false;
      if (b)
        throw Error(n(300));
      return a;
    }
    function Me() {
      var a = Ee !== 0;
      Ee = 0;
      return a;
    }
    function Ne() {
      var a = { memoizedState: null, baseState: null, baseQueue: null, queue: null, next: null };
      L === null ? J.memoizedState = L = a : L = L.next = a;
      return L;
    }
    function Oe() {
      if (K === null) {
        var a = J.alternate;
        a = a !== null ? a.memoizedState : null;
      } else
        a = K.next;
      var b = L === null ? J.memoizedState : L.next;
      if (b !== null)
        L = b, K = a;
      else {
        if (a === null)
          throw Error(n(310));
        K = a;
        a = { memoizedState: K.memoizedState, baseState: K.baseState, baseQueue: K.baseQueue, queue: K.queue, next: null };
        L === null ? J.memoizedState = L = a : L = L.next = a;
      }
      return L;
    }
    function Pe(a, b) {
      return typeof b === "function" ? b(a) : b;
    }
    function Qe(a) {
      var b = Oe(), c = b.queue;
      if (c === null)
        throw Error(n(311));
      c.lastRenderedReducer = a;
      var d = K, e = d.baseQueue, f = c.pending;
      if (f !== null) {
        if (e !== null) {
          var g = e.next;
          e.next = f.next;
          f.next = g;
        }
        d.baseQueue = e = f;
        c.pending = null;
      }
      if (e !== null) {
        f = e.next;
        d = d.baseState;
        var h = g = null, k = null, l = f;
        do {
          var m = l.lane;
          if ((Be & m) === m)
            k !== null && (k = k.next = { lane: 0, action: l.action, hasEagerState: l.hasEagerState, eagerState: l.eagerState, next: null }), d = l.hasEagerState ? l.eagerState : a(d, l.action);
          else {
            var r = {
              lane: m,
              action: l.action,
              hasEagerState: l.hasEagerState,
              eagerState: l.eagerState,
              next: null
            };
            k === null ? (h = k = r, g = d) : k = k.next = r;
            J.lanes |= m;
            le |= m;
          }
          l = l.next;
        } while (l !== null && l !== f);
        k === null ? g = d : k.next = h;
        Vc(d, b.memoizedState) || (G = true);
        b.memoizedState = d;
        b.baseState = g;
        b.baseQueue = k;
        c.lastRenderedState = d;
      }
      a = c.interleaved;
      if (a !== null) {
        e = a;
        do
          f = e.lane, J.lanes |= f, le |= f, e = e.next;
        while (e !== a);
      } else
        e === null && (c.lanes = 0);
      return [b.memoizedState, c.dispatch];
    }
    function Re(a) {
      var b = Oe(), c = b.queue;
      if (c === null)
        throw Error(n(311));
      c.lastRenderedReducer = a;
      var { dispatch: d, pending: e } = c, f = b.memoizedState;
      if (e !== null) {
        c.pending = null;
        var g = e = e.next;
        do
          f = a(f, g.action), g = g.next;
        while (g !== e);
        Vc(f, b.memoizedState) || (G = true);
        b.memoizedState = f;
        b.baseQueue === null && (b.baseState = f);
        c.lastRenderedState = f;
      }
      return [f, d];
    }
    function Se() {}
    function Te(a, b) {
      var c = J, d = Oe(), e = b(), f = !Vc(d.memoizedState, e);
      f && (d.memoizedState = e, G = true);
      d = d.queue;
      Ue(Ve.bind(null, c, d, a), [a]);
      if (d.getSnapshot !== b || f || L !== null && L.memoizedState.tag & 1) {
        c.flags |= 2048;
        We(9, Xe.bind(null, c, d, e, b), undefined, null);
        if (N === null)
          throw Error(n(349));
        (Be & 30) !== 0 || Ye(c, b, e);
      }
      return e;
    }
    function Ye(a, b, c) {
      a.flags |= 16384;
      a = { getSnapshot: b, value: c };
      b = J.updateQueue;
      b === null ? (b = { lastEffect: null, stores: null }, J.updateQueue = b, b.stores = [a]) : (c = b.stores, c === null ? b.stores = [a] : c.push(a));
    }
    function Xe(a, b, c, d) {
      b.value = c;
      b.getSnapshot = d;
      Ze(b) && $e(a);
    }
    function Ve(a, b, c) {
      return c(function() {
        Ze(b) && $e(a);
      });
    }
    function Ze(a) {
      var b = a.getSnapshot;
      a = a.value;
      try {
        var c = b();
        return !Vc(a, c);
      } catch (d) {
        return true;
      }
    }
    function $e(a) {
      var b = ce(a, 1);
      b !== null && af(b, a, 1, -1);
    }
    function bf(a) {
      var b = Ne();
      typeof a === "function" && (a = a());
      b.memoizedState = b.baseState = a;
      a = { pending: null, interleaved: null, lanes: 0, dispatch: null, lastRenderedReducer: Pe, lastRenderedState: a };
      b.queue = a;
      a = a.dispatch = cf.bind(null, J, a);
      return [b.memoizedState, a];
    }
    function We(a, b, c, d) {
      a = { tag: a, create: b, destroy: c, deps: d, next: null };
      b = J.updateQueue;
      b === null ? (b = { lastEffect: null, stores: null }, J.updateQueue = b, b.lastEffect = a.next = a) : (c = b.lastEffect, c === null ? b.lastEffect = a.next = a : (d = c.next, c.next = a, a.next = d, b.lastEffect = a));
      return a;
    }
    function df() {
      return Oe().memoizedState;
    }
    function ef(a, b, c, d) {
      var e = Ne();
      J.flags |= a;
      e.memoizedState = We(1 | b, c, undefined, d === undefined ? null : d);
    }
    function ff(a, b, c, d) {
      var e = Oe();
      d = d === undefined ? null : d;
      var f = undefined;
      if (K !== null) {
        var g = K.memoizedState;
        f = g.destroy;
        if (d !== null && Ge(d, g.deps)) {
          e.memoizedState = We(b, c, f, d);
          return;
        }
      }
      J.flags |= a;
      e.memoizedState = We(1 | b, c, f, d);
    }
    function gf(a, b) {
      return ef(8390656, 8, a, b);
    }
    function Ue(a, b) {
      return ff(2048, 8, a, b);
    }
    function hf(a, b) {
      return ff(4, 2, a, b);
    }
    function jf(a, b) {
      return ff(4, 4, a, b);
    }
    function kf(a, b) {
      if (typeof b === "function")
        return a = a(), b(a), function() {
          b(null);
        };
      if (b !== null && b !== undefined)
        return a = a(), b.current = a, function() {
          b.current = null;
        };
    }
    function lf(a, b, c) {
      c = c !== null && c !== undefined ? c.concat([a]) : null;
      return ff(4, 4, kf.bind(null, b, a), c);
    }
    function mf() {}
    function nf(a, b) {
      var c = Oe();
      b = b === undefined ? null : b;
      var d = c.memoizedState;
      if (d !== null && b !== null && Ge(b, d[1]))
        return d[0];
      c.memoizedState = [a, b];
      return a;
    }
    function of(a, b) {
      var c = Oe();
      b = b === undefined ? null : b;
      var d = c.memoizedState;
      if (d !== null && b !== null && Ge(b, d[1]))
        return d[0];
      a = a();
      c.memoizedState = [a, b];
      return a;
    }
    function pf(a, b, c) {
      if ((Be & 21) === 0)
        return a.baseState && (a.baseState = false, G = true), a.memoizedState = c;
      Vc(c, b) || (c = Dc(), J.lanes |= c, le |= c, a.baseState = true);
      return b;
    }
    function qf(a, b) {
      var c = C;
      C = c !== 0 && 4 > c ? c : 4;
      a(true);
      var d = Ae.transition;
      Ae.transition = {};
      try {
        a(false), b();
      } finally {
        C = c, Ae.transition = d;
      }
    }
    function rf() {
      return Oe().memoizedState;
    }
    function sf(a, b, c) {
      var d = tf(a);
      c = { lane: d, action: c, hasEagerState: false, eagerState: null, next: null };
      if (uf(a))
        vf(b, c);
      else if (c = be(a, b, c, d), c !== null) {
        var e = O();
        af(c, a, d, e);
        wf(c, b, d);
      }
    }
    function cf(a, b, c) {
      var d = tf(a), e = { lane: d, action: c, hasEagerState: false, eagerState: null, next: null };
      if (uf(a))
        vf(b, e);
      else {
        var f = a.alternate;
        if (a.lanes === 0 && (f === null || f.lanes === 0) && (f = b.lastRenderedReducer, f !== null))
          try {
            var g = b.lastRenderedState, h = f(g, c);
            e.hasEagerState = true;
            e.eagerState = h;
            if (Vc(h, g)) {
              var k = b.interleaved;
              k === null ? (e.next = e, ae(b)) : (e.next = k.next, k.next = e);
              b.interleaved = e;
              return;
            }
          } catch (l) {} finally {}
        c = be(a, b, e, d);
        c !== null && (e = O(), af(c, a, d, e), wf(c, b, d));
      }
    }
    function uf(a) {
      var b = a.alternate;
      return a === J || b !== null && b === J;
    }
    function vf(a, b) {
      De = Ce = true;
      var c = a.pending;
      c === null ? b.next = b : (b.next = c.next, c.next = b);
      a.pending = b;
    }
    function wf(a, b, c) {
      if ((c & 4194240) !== 0) {
        var d = b.lanes;
        d &= a.pendingLanes;
        c |= d;
        b.lanes = c;
        Hc(a, c);
      }
    }
    var Le = { readContext: Zd, useCallback: M, useContext: M, useEffect: M, useImperativeHandle: M, useInsertionEffect: M, useLayoutEffect: M, useMemo: M, useReducer: M, useRef: M, useState: M, useDebugValue: M, useDeferredValue: M, useTransition: M, useMutableSource: M, useSyncExternalStore: M, useId: M, unstable_isNewReconciler: false }, Ie = { readContext: Zd, useCallback: function(a, b) {
      Ne().memoizedState = [a, b === undefined ? null : b];
      return a;
    }, useContext: Zd, useEffect: gf, useImperativeHandle: function(a, b, c) {
      c = c !== null && c !== undefined ? c.concat([a]) : null;
      return ef(4194308, 4, kf.bind(null, b, a), c);
    }, useLayoutEffect: function(a, b) {
      return ef(4194308, 4, a, b);
    }, useInsertionEffect: function(a, b) {
      return ef(4, 2, a, b);
    }, useMemo: function(a, b) {
      var c = Ne();
      b = b === undefined ? null : b;
      a = a();
      c.memoizedState = [a, b];
      return a;
    }, useReducer: function(a, b, c) {
      var d = Ne();
      b = c !== undefined ? c(b) : b;
      d.memoizedState = d.baseState = b;
      a = { pending: null, interleaved: null, lanes: 0, dispatch: null, lastRenderedReducer: a, lastRenderedState: b };
      d.queue = a;
      a = a.dispatch = sf.bind(null, J, a);
      return [d.memoizedState, a];
    }, useRef: function(a) {
      var b = Ne();
      a = { current: a };
      return b.memoizedState = a;
    }, useState: bf, useDebugValue: mf, useDeferredValue: function(a) {
      return Ne().memoizedState = a;
    }, useTransition: function() {
      var a = bf(false), b = a[0];
      a = qf.bind(null, a[1]);
      Ne().memoizedState = a;
      return [b, a];
    }, useMutableSource: function() {}, useSyncExternalStore: function(a, b, c) {
      var d = J, e = Ne();
      if (F) {
        if (c === undefined)
          throw Error(n(407));
        c = c();
      } else {
        c = b();
        if (N === null)
          throw Error(n(349));
        (Be & 30) !== 0 || Ye(d, b, c);
      }
      e.memoizedState = c;
      var f = { value: c, getSnapshot: b };
      e.queue = f;
      gf(Ve.bind(null, d, f, a), [a]);
      d.flags |= 2048;
      We(9, Xe.bind(null, d, f, c, b), undefined, null);
      return c;
    }, useId: function() {
      var a = Ne(), b = N.identifierPrefix;
      if (F) {
        var c = jd;
        var d = id;
        c = (d & ~(1 << 32 - tc(d) - 1)).toString(32) + c;
        b = ":" + b + "R" + c;
        c = Ee++;
        0 < c && (b += "H" + c.toString(32));
        b += ":";
      } else
        c = Fe++, b = ":" + b + "r" + c.toString(32) + ":";
      return a.memoizedState = b;
    }, unstable_isNewReconciler: false }, Je = {
      readContext: Zd,
      useCallback: nf,
      useContext: Zd,
      useEffect: Ue,
      useImperativeHandle: lf,
      useInsertionEffect: hf,
      useLayoutEffect: jf,
      useMemo: of,
      useReducer: Qe,
      useRef: df,
      useState: function() {
        return Qe(Pe);
      },
      useDebugValue: mf,
      useDeferredValue: function(a) {
        var b = Oe();
        return pf(b, K.memoizedState, a);
      },
      useTransition: function() {
        var a = Qe(Pe)[0], b = Oe().memoizedState;
        return [a, b];
      },
      useMutableSource: Se,
      useSyncExternalStore: Te,
      useId: rf,
      unstable_isNewReconciler: false
    }, Ke = { readContext: Zd, useCallback: nf, useContext: Zd, useEffect: Ue, useImperativeHandle: lf, useInsertionEffect: hf, useLayoutEffect: jf, useMemo: of, useReducer: Re, useRef: df, useState: function() {
      return Re(Pe);
    }, useDebugValue: mf, useDeferredValue: function(a) {
      var b = Oe();
      return K === null ? b.memoizedState = a : pf(b, K.memoizedState, a);
    }, useTransition: function() {
      var a = Re(Pe)[0], b = Oe().memoizedState;
      return [a, b];
    }, useMutableSource: Se, useSyncExternalStore: Te, useId: rf, unstable_isNewReconciler: false };
    function xf(a, b) {
      if (a && a.defaultProps) {
        b = ca({}, b);
        a = a.defaultProps;
        for (var c in a)
          b[c] === undefined && (b[c] = a[c]);
        return b;
      }
      return b;
    }
    function yf(a, b, c, d) {
      b = a.memoizedState;
      c = c(d, b);
      c = c === null || c === undefined ? b : ca({}, b, c);
      a.memoizedState = c;
      a.lanes === 0 && (a.updateQueue.baseState = c);
    }
    var zf = { isMounted: function(a) {
      return (a = a._reactInternals) ? wa(a) === a : false;
    }, enqueueSetState: function(a, b, c) {
      a = a._reactInternals;
      var d = O(), e = tf(a), f = ge(d, e);
      f.payload = b;
      c !== undefined && c !== null && (f.callback = c);
      b = he(a, f, e);
      b !== null && (af(b, a, e, d), ie(b, a, e));
    }, enqueueReplaceState: function(a, b, c) {
      a = a._reactInternals;
      var d = O(), e = tf(a), f = ge(d, e);
      f.tag = 1;
      f.payload = b;
      c !== undefined && c !== null && (f.callback = c);
      b = he(a, f, e);
      b !== null && (af(b, a, e, d), ie(b, a, e));
    }, enqueueForceUpdate: function(a, b) {
      a = a._reactInternals;
      var c = O(), d = tf(a), e = ge(c, d);
      e.tag = 2;
      b !== undefined && b !== null && (e.callback = b);
      b = he(a, e, d);
      b !== null && (af(b, a, d, c), ie(b, a, d));
    } };
    function Af(a, b, c, d, e, f, g) {
      a = a.stateNode;
      return typeof a.shouldComponentUpdate === "function" ? a.shouldComponentUpdate(d, f, g) : b.prototype && b.prototype.isPureReactComponent ? !Dd(c, d) || !Dd(e, f) : true;
    }
    function Bf(a, b, c) {
      var d = false, e = jc;
      var f = b.contextType;
      typeof f === "object" && f !== null ? f = Zd(f) : (e = A(b) ? kc : x.current, d = b.contextTypes, f = (d = d !== null && d !== undefined) ? mc(a, e) : jc);
      b = new b(c, f);
      a.memoizedState = b.state !== null && b.state !== undefined ? b.state : null;
      b.updater = zf;
      a.stateNode = b;
      b._reactInternals = a;
      d && (a = a.stateNode, a.__reactInternalMemoizedUnmaskedChildContext = e, a.__reactInternalMemoizedMaskedChildContext = f);
      return b;
    }
    function Cf(a, b, c, d) {
      a = b.state;
      typeof b.componentWillReceiveProps === "function" && b.componentWillReceiveProps(c, d);
      typeof b.UNSAFE_componentWillReceiveProps === "function" && b.UNSAFE_componentWillReceiveProps(c, d);
      b.state !== a && zf.enqueueReplaceState(b, b.state, null);
    }
    function Df(a, b, c, d) {
      var e = a.stateNode;
      e.props = c;
      e.state = a.memoizedState;
      e.refs = {};
      ee(a);
      var f = b.contextType;
      typeof f === "object" && f !== null ? e.context = Zd(f) : (f = A(b) ? kc : x.current, e.context = mc(a, f));
      e.state = a.memoizedState;
      f = b.getDerivedStateFromProps;
      typeof f === "function" && (yf(a, b, f, c), e.state = a.memoizedState);
      typeof b.getDerivedStateFromProps === "function" || typeof e.getSnapshotBeforeUpdate === "function" || typeof e.UNSAFE_componentWillMount !== "function" && typeof e.componentWillMount !== "function" || (b = e.state, typeof e.componentWillMount === "function" && e.componentWillMount(), typeof e.UNSAFE_componentWillMount === "function" && e.UNSAFE_componentWillMount(), b !== e.state && zf.enqueueReplaceState(e, e.state, null), ke(a, c, e, d), e.state = a.memoizedState);
      typeof e.componentDidMount === "function" && (a.flags |= 4194308);
    }
    function Ef(a, b) {
      try {
        var c = "", d = b;
        do
          c += Ed(d), d = d.return;
        while (d);
        var e = c;
      } catch (f) {
        e = `
Error generating stack: ` + f.message + `
` + f.stack;
      }
      return { value: a, source: b, stack: e, digest: null };
    }
    function Ff(a, b, c) {
      return { value: a, source: null, stack: c != null ? c : null, digest: b != null ? b : null };
    }
    function Gf(a, b) {
      try {
        console.error(b.value);
      } catch (c) {
        setTimeout(function() {
          throw c;
        });
      }
    }
    var Hf = typeof WeakMap === "function" ? WeakMap : Map;
    function If(a, b, c) {
      c = ge(-1, c);
      c.tag = 3;
      c.payload = { element: null };
      var d = b.value;
      c.callback = function() {
        Jf || (Jf = true, Kf = d);
        Gf(a, b);
      };
      return c;
    }
    function Lf(a, b, c) {
      c = ge(-1, c);
      c.tag = 3;
      var d = a.type.getDerivedStateFromError;
      if (typeof d === "function") {
        var e = b.value;
        c.payload = function() {
          return d(e);
        };
        c.callback = function() {
          Gf(a, b);
        };
      }
      var f = a.stateNode;
      f !== null && typeof f.componentDidCatch === "function" && (c.callback = function() {
        Gf(a, b);
        typeof d !== "function" && (Mf === null ? Mf = new Set([this]) : Mf.add(this));
        var c2 = b.stack;
        this.componentDidCatch(b.value, { componentStack: c2 !== null ? c2 : "" });
      });
      return c;
    }
    function Nf(a, b, c) {
      var d = a.pingCache;
      if (d === null) {
        d = a.pingCache = new Hf;
        var e = new Set;
        d.set(b, e);
      } else
        e = d.get(b), e === undefined && (e = new Set, d.set(b, e));
      e.has(c) || (e.add(c), a = Of.bind(null, a, b, c), b.then(a, a));
    }
    function Pf(a) {
      do {
        var b;
        if (b = a.tag === 13)
          b = a.memoizedState, b = b !== null ? b.dehydrated !== null ? true : false : true;
        if (b)
          return a;
        a = a.return;
      } while (a !== null);
      return null;
    }
    function Qf(a, b, c, d, e) {
      if ((a.mode & 1) === 0)
        return a === b ? a.flags |= 65536 : (a.flags |= 128, c.flags |= 131072, c.flags &= -52805, c.tag === 1 && (c.alternate === null ? c.tag = 17 : (b = ge(-1, 1), b.tag = 2, he(c, b, 1))), c.lanes |= 1), a;
      a.flags |= 65536;
      a.lanes = e;
      return a;
    }
    var Rf = da.ReactCurrentOwner, G = false;
    function P(a, b, c, d) {
      b.child = a === null ? Pd(b, null, c, d) : Od(b, a.child, c, d);
    }
    function Sf(a, b, c, d, e) {
      c = c.render;
      var f = b.ref;
      Yd(b, e);
      d = He(a, b, c, d, f, e);
      c = Me();
      if (a !== null && !G)
        return b.updateQueue = a.updateQueue, b.flags &= -2053, a.lanes &= ~e, Tf(a, b, e);
      F && c && md(b);
      b.flags |= 1;
      P(a, b, d, e);
      return b.child;
    }
    function Uf(a, b, c, d, e) {
      if (a === null) {
        var f = c.type;
        if (typeof f === "function" && !Vf(f) && f.defaultProps === undefined && c.compare === null && c.defaultProps === undefined)
          return b.tag = 15, b.type = f, Wf(a, b, f, d, e);
        a = Ld(c.type, null, d, b, b.mode, e);
        a.ref = b.ref;
        a.return = b;
        return b.child = a;
      }
      f = a.child;
      if ((a.lanes & e) === 0) {
        var g = f.memoizedProps;
        c = c.compare;
        c = c !== null ? c : Dd;
        if (c(g, d) && a.ref === b.ref)
          return Tf(a, b, e);
      }
      b.flags |= 1;
      a = Jd(f, d);
      a.ref = b.ref;
      a.return = b;
      return b.child = a;
    }
    function Wf(a, b, c, d, e) {
      if (a !== null) {
        var f = a.memoizedProps;
        if (Dd(f, d) && a.ref === b.ref)
          if (G = false, b.pendingProps = d = f, (a.lanes & e) !== 0)
            (a.flags & 131072) !== 0 && (G = true);
          else
            return b.lanes = a.lanes, Tf(a, b, e);
      }
      return Xf(a, b, c, d, e);
    }
    function Yf(a, b, c) {
      var d = b.pendingProps, e = d.children, f = a !== null ? a.memoizedState : null;
      if (d.mode === "hidden")
        if ((b.mode & 1) === 0)
          b.memoizedState = { baseLanes: 0, cachePool: null, transitions: null }, v(Zf, $f), $f |= c;
        else {
          if ((c & 1073741824) === 0)
            return a = f !== null ? f.baseLanes | c : c, b.lanes = b.childLanes = 1073741824, b.memoizedState = { baseLanes: a, cachePool: null, transitions: null }, b.updateQueue = null, v(Zf, $f), $f |= a, null;
          b.memoizedState = { baseLanes: 0, cachePool: null, transitions: null };
          d = f !== null ? f.baseLanes : c;
          v(Zf, $f);
          $f |= d;
        }
      else
        f !== null ? (d = f.baseLanes | c, b.memoizedState = null) : d = c, v(Zf, $f), $f |= d;
      P(a, b, e, c);
      return b.child;
    }
    function ag(a, b) {
      var c = b.ref;
      if (a === null && c !== null || a !== null && a.ref !== c)
        b.flags |= 512, b.flags |= 2097152;
    }
    function Xf(a, b, c, d, e) {
      var f = A(c) ? kc : x.current;
      f = mc(b, f);
      Yd(b, e);
      c = He(a, b, c, d, f, e);
      d = Me();
      if (a !== null && !G)
        return b.updateQueue = a.updateQueue, b.flags &= -2053, a.lanes &= ~e, Tf(a, b, e);
      F && d && md(b);
      b.flags |= 1;
      P(a, b, c, e);
      return b.child;
    }
    function bg(a, b, c, d, e) {
      if (A(c)) {
        var f = true;
        qc(b);
      } else
        f = false;
      Yd(b, e);
      if (b.stateNode === null)
        cg(a, b), Bf(b, c, d), Df(b, c, d, e), d = true;
      else if (a === null) {
        var { stateNode: g, memoizedProps: h } = b;
        g.props = h;
        var k = g.context, l = c.contextType;
        typeof l === "object" && l !== null ? l = Zd(l) : (l = A(c) ? kc : x.current, l = mc(b, l));
        var m = c.getDerivedStateFromProps, r = typeof m === "function" || typeof g.getSnapshotBeforeUpdate === "function";
        r || typeof g.UNSAFE_componentWillReceiveProps !== "function" && typeof g.componentWillReceiveProps !== "function" || (h !== d || k !== l) && Cf(b, g, d, l);
        de = false;
        var p = b.memoizedState;
        g.state = p;
        ke(b, d, g, e);
        k = b.memoizedState;
        h !== d || p !== k || z.current || de ? (typeof m === "function" && (yf(b, c, m, d), k = b.memoizedState), (h = de || Af(b, c, h, d, p, k, l)) ? (r || typeof g.UNSAFE_componentWillMount !== "function" && typeof g.componentWillMount !== "function" || (typeof g.componentWillMount === "function" && g.componentWillMount(), typeof g.UNSAFE_componentWillMount === "function" && g.UNSAFE_componentWillMount()), typeof g.componentDidMount === "function" && (b.flags |= 4194308)) : (typeof g.componentDidMount === "function" && (b.flags |= 4194308), b.memoizedProps = d, b.memoizedState = k), g.props = d, g.state = k, g.context = l, d = h) : (typeof g.componentDidMount === "function" && (b.flags |= 4194308), d = false);
      } else {
        g = b.stateNode;
        fe(a, b);
        h = b.memoizedProps;
        l = b.type === b.elementType ? h : xf(b.type, h);
        g.props = l;
        r = b.pendingProps;
        p = g.context;
        k = c.contextType;
        typeof k === "object" && k !== null ? k = Zd(k) : (k = A(c) ? kc : x.current, k = mc(b, k));
        var B = c.getDerivedStateFromProps;
        (m = typeof B === "function" || typeof g.getSnapshotBeforeUpdate === "function") || typeof g.UNSAFE_componentWillReceiveProps !== "function" && typeof g.componentWillReceiveProps !== "function" || (h !== r || p !== k) && Cf(b, g, d, k);
        de = false;
        p = b.memoizedState;
        g.state = p;
        ke(b, d, g, e);
        var w = b.memoizedState;
        h !== r || p !== w || z.current || de ? (typeof B === "function" && (yf(b, c, B, d), w = b.memoizedState), (l = de || Af(b, c, l, d, p, w, k) || false) ? (m || typeof g.UNSAFE_componentWillUpdate !== "function" && typeof g.componentWillUpdate !== "function" || (typeof g.componentWillUpdate === "function" && g.componentWillUpdate(d, w, k), typeof g.UNSAFE_componentWillUpdate === "function" && g.UNSAFE_componentWillUpdate(d, w, k)), typeof g.componentDidUpdate === "function" && (b.flags |= 4), typeof g.getSnapshotBeforeUpdate === "function" && (b.flags |= 1024)) : (typeof g.componentDidUpdate !== "function" || h === a.memoizedProps && p === a.memoizedState || (b.flags |= 4), typeof g.getSnapshotBeforeUpdate !== "function" || h === a.memoizedProps && p === a.memoizedState || (b.flags |= 1024), b.memoizedProps = d, b.memoizedState = w), g.props = d, g.state = w, g.context = k, d = l) : (typeof g.componentDidUpdate !== "function" || h === a.memoizedProps && p === a.memoizedState || (b.flags |= 4), typeof g.getSnapshotBeforeUpdate !== "function" || h === a.memoizedProps && p === a.memoizedState || (b.flags |= 1024), d = false);
      }
      return dg(a, b, c, d, f, e);
    }
    function dg(a, b, c, d, e, f) {
      ag(a, b);
      var g = (b.flags & 128) !== 0;
      if (!d && !g)
        return e && rc(b, c, false), Tf(a, b, f);
      d = b.stateNode;
      Rf.current = b;
      var h = g && typeof c.getDerivedStateFromError !== "function" ? null : d.render();
      b.flags |= 1;
      a !== null && g ? (b.child = Od(b, a.child, null, f), b.child = Od(b, null, h, f)) : P(a, b, h, f);
      b.memoizedState = d.state;
      e && rc(b, c, true);
      return b.child;
    }
    function eg(a) {
      var b = a.stateNode;
      b.pendingContext ? oc(a, b.pendingContext, b.pendingContext !== b.context) : b.context && oc(a, b.context, false);
      se(a, b.containerInfo);
    }
    function fg(a, b, c, d, e) {
      Ad();
      Bd(e);
      b.flags |= 256;
      P(a, b, c, d);
      return b.child;
    }
    var gg = { dehydrated: null, treeContext: null, retryLane: 0 };
    function hg(a) {
      return { baseLanes: a, cachePool: null, transitions: null };
    }
    function ig(a, b, c) {
      var d = b.pendingProps, e = I.current, f = false, g = (b.flags & 128) !== 0, h;
      (h = g) || (h = a !== null && a.memoizedState === null ? false : (e & 2) !== 0);
      if (h)
        f = true, b.flags &= -129;
      else if (a === null || a.memoizedState !== null)
        e |= 1;
      v(I, e & 1);
      if (a === null) {
        wd(b);
        a = b.memoizedState;
        if (a !== null && (a = a.dehydrated, a !== null))
          return (b.mode & 1) === 0 ? b.lanes = 1 : Kb(a) ? b.lanes = 8 : b.lanes = 1073741824, null;
        g = d.children;
        a = d.fallback;
        return f ? (d = b.mode, f = b.child, g = { mode: "hidden", children: g }, (d & 1) === 0 && f !== null ? (f.childLanes = 0, f.pendingProps = g) : f = jg(g, d, 0, null), a = Nd(a, d, c, null), f.return = b, a.return = b, f.sibling = a, b.child = f, b.child.memoizedState = hg(c), b.memoizedState = gg, a) : kg(b, g);
      }
      e = a.memoizedState;
      if (e !== null && (h = e.dehydrated, h !== null))
        return lg(a, b, g, d, h, e, c);
      if (f) {
        f = d.fallback;
        g = b.mode;
        e = a.child;
        h = e.sibling;
        var k = { mode: "hidden", children: d.children };
        (g & 1) === 0 && b.child !== e ? (d = b.child, d.childLanes = 0, d.pendingProps = k, b.deletions = null) : (d = Jd(e, k), d.subtreeFlags = e.subtreeFlags & 14680064);
        h !== null ? f = Jd(h, f) : (f = Nd(f, g, c, null), f.flags |= 2);
        f.return = b;
        d.return = b;
        d.sibling = f;
        b.child = d;
        d = f;
        f = b.child;
        g = a.child.memoizedState;
        g = g === null ? hg(c) : { baseLanes: g.baseLanes | c, cachePool: null, transitions: g.transitions };
        f.memoizedState = g;
        f.childLanes = a.childLanes & ~c;
        b.memoizedState = gg;
        return d;
      }
      f = a.child;
      a = f.sibling;
      d = Jd(f, { mode: "visible", children: d.children });
      (b.mode & 1) === 0 && (d.lanes = c);
      d.return = b;
      d.sibling = null;
      a !== null && (c = b.deletions, c === null ? (b.deletions = [a], b.flags |= 16) : c.push(a));
      b.child = d;
      b.memoizedState = null;
      return d;
    }
    function kg(a, b) {
      b = jg({ mode: "visible", children: b }, a.mode, 0, null);
      b.return = a;
      return a.child = b;
    }
    function mg(a, b, c, d) {
      d !== null && Bd(d);
      Od(b, a.child, null, c);
      a = kg(b, b.pendingProps.children);
      a.flags |= 2;
      b.memoizedState = null;
      return a;
    }
    function lg(a, b, c, d, e, f, g) {
      if (c) {
        if (b.flags & 256)
          return b.flags &= -257, d = Ff(Error(n(422))), mg(a, b, g, d);
        if (b.memoizedState !== null)
          return b.child = a.child, b.flags |= 128, null;
        f = d.fallback;
        e = b.mode;
        d = jg({ mode: "visible", children: d.children }, e, 0, null);
        f = Nd(f, e, g, null);
        f.flags |= 2;
        d.return = b;
        f.return = b;
        d.sibling = f;
        b.child = d;
        (b.mode & 1) !== 0 && Od(b, a.child, null, g);
        b.child.memoizedState = hg(g);
        b.memoizedState = gg;
        return f;
      }
      if ((b.mode & 1) === 0)
        return mg(a, b, g, null);
      if (Kb(e))
        return d = Lb(e).digest, f = Error(n(419)), d = Ff(f, d, undefined), mg(a, b, g, d);
      c = (g & a.childLanes) !== 0;
      if (G || c) {
        d = N;
        if (d !== null) {
          switch (g & -g) {
            case 4:
              e = 2;
              break;
            case 16:
              e = 8;
              break;
            case 64:
            case 128:
            case 256:
            case 512:
            case 1024:
            case 2048:
            case 4096:
            case 8192:
            case 16384:
            case 32768:
            case 65536:
            case 131072:
            case 262144:
            case 524288:
            case 1048576:
            case 2097152:
            case 4194304:
            case 8388608:
            case 16777216:
            case 33554432:
            case 67108864:
              e = 32;
              break;
            case 536870912:
              e = 268435456;
              break;
            default:
              e = 0;
          }
          e = (e & (d.suspendedLanes | g)) !== 0 ? 0 : e;
          e !== 0 && e !== f.retryLane && (f.retryLane = e, ce(a, e), af(d, a, e, -1));
        }
        ng();
        d = Ff(Error(n(421)));
        return mg(a, b, g, d);
      }
      if (Jb(e))
        return b.flags |= 128, b.child = a.child, b = og.bind(null, a), Mb(e, b), null;
      a = f.treeContext;
      Va && (pd = Qb(e), od = b, F = true, rd = null, qd = false, a !== null && (fd[gd++] = id, fd[gd++] = jd, fd[gd++] = hd, id = a.id, jd = a.overflow, hd = b));
      b = kg(b, d.children);
      b.flags |= 4096;
      return b;
    }
    function pg(a, b, c) {
      a.lanes |= b;
      var d = a.alternate;
      d !== null && (d.lanes |= b);
      Xd(a.return, b, c);
    }
    function qg(a, b, c, d, e) {
      var f = a.memoizedState;
      f === null ? a.memoizedState = { isBackwards: b, rendering: null, renderingStartTime: 0, last: d, tail: c, tailMode: e } : (f.isBackwards = b, f.rendering = null, f.renderingStartTime = 0, f.last = d, f.tail = c, f.tailMode = e);
    }
    function rg(a, b, c) {
      var d = b.pendingProps, e = d.revealOrder, f = d.tail;
      P(a, b, d.children, c);
      d = I.current;
      if ((d & 2) !== 0)
        d = d & 1 | 2, b.flags |= 128;
      else {
        if (a !== null && (a.flags & 128) !== 0)
          a:
            for (a = b.child;a !== null; ) {
              if (a.tag === 13)
                a.memoizedState !== null && pg(a, c, b);
              else if (a.tag === 19)
                pg(a, c, b);
              else if (a.child !== null) {
                a.child.return = a;
                a = a.child;
                continue;
              }
              if (a === b)
                break a;
              for (;a.sibling === null; ) {
                if (a.return === null || a.return === b)
                  break a;
                a = a.return;
              }
              a.sibling.return = a.return;
              a = a.sibling;
            }
        d &= 1;
      }
      v(I, d);
      if ((b.mode & 1) === 0)
        b.memoizedState = null;
      else
        switch (e) {
          case "forwards":
            c = b.child;
            for (e = null;c !== null; )
              a = c.alternate, a !== null && we(a) === null && (e = c), c = c.sibling;
            c = e;
            c === null ? (e = b.child, b.child = null) : (e = c.sibling, c.sibling = null);
            qg(b, false, e, c, f);
            break;
          case "backwards":
            c = null;
            e = b.child;
            for (b.child = null;e !== null; ) {
              a = e.alternate;
              if (a !== null && we(a) === null) {
                b.child = e;
                break;
              }
              a = e.sibling;
              e.sibling = c;
              c = e;
              e = a;
            }
            qg(b, true, c, null, f);
            break;
          case "together":
            qg(b, false, null, null, undefined);
            break;
          default:
            b.memoizedState = null;
        }
      return b.child;
    }
    function cg(a, b) {
      (b.mode & 1) === 0 && a !== null && (a.alternate = null, b.alternate = null, b.flags |= 2);
    }
    function Tf(a, b, c) {
      a !== null && (b.dependencies = a.dependencies);
      le |= b.lanes;
      if ((c & b.childLanes) === 0)
        return null;
      if (a !== null && b.child !== a.child)
        throw Error(n(153));
      if (b.child !== null) {
        a = b.child;
        c = Jd(a, a.pendingProps);
        b.child = c;
        for (c.return = b;a.sibling !== null; )
          a = a.sibling, c = c.sibling = Jd(a, a.pendingProps), c.return = b;
        c.sibling = null;
      }
      return b.child;
    }
    function sg(a, b, c) {
      switch (b.tag) {
        case 3:
          eg(b);
          Ad();
          break;
        case 5:
          ue(b);
          break;
        case 1:
          A(b.type) && qc(b);
          break;
        case 4:
          se(b, b.stateNode.containerInfo);
          break;
        case 10:
          Vd(b, b.type._context, b.memoizedProps.value);
          break;
        case 13:
          var d = b.memoizedState;
          if (d !== null) {
            if (d.dehydrated !== null)
              return v(I, I.current & 1), b.flags |= 128, null;
            if ((c & b.child.childLanes) !== 0)
              return ig(a, b, c);
            v(I, I.current & 1);
            a = Tf(a, b, c);
            return a !== null ? a.sibling : null;
          }
          v(I, I.current & 1);
          break;
        case 19:
          d = (c & b.childLanes) !== 0;
          if ((a.flags & 128) !== 0) {
            if (d)
              return rg(a, b, c);
            b.flags |= 128;
          }
          var e = b.memoizedState;
          e !== null && (e.rendering = null, e.tail = null, e.lastEffect = null);
          v(I, I.current);
          if (d)
            break;
          else
            return null;
        case 22:
        case 23:
          return b.lanes = 0, Yf(a, b, c);
      }
      return Tf(a, b, c);
    }
    function tg(a) {
      a.flags |= 4;
    }
    function ug(a, b) {
      if (a !== null && a.child === b.child)
        return true;
      if ((b.flags & 16) !== 0)
        return false;
      for (a = b.child;a !== null; ) {
        if ((a.flags & 12854) !== 0 || (a.subtreeFlags & 12854) !== 0)
          return false;
        a = a.sibling;
      }
      return true;
    }
    var vg, wg, xg, yg;
    if (Ta)
      vg = function(a, b) {
        for (var c = b.child;c !== null; ) {
          if (c.tag === 5 || c.tag === 6)
            Ka(a, c.stateNode);
          else if (c.tag !== 4 && c.child !== null) {
            c.child.return = c;
            c = c.child;
            continue;
          }
          if (c === b)
            break;
          for (;c.sibling === null; ) {
            if (c.return === null || c.return === b)
              return;
            c = c.return;
          }
          c.sibling.return = c.return;
          c = c.sibling;
        }
      }, wg = function() {}, xg = function(a, b, c, d, e) {
        a = a.memoizedProps;
        if (a !== d) {
          var f = b.stateNode, g = re(oe.current);
          c = Ma(f, c, a, d, e, g);
          (b.updateQueue = c) && tg(b);
        }
      }, yg = function(a, b, c, d) {
        c !== d && tg(b);
      };
    else if (Ua) {
      vg = function(a, b, c, d) {
        for (var e = b.child;e !== null; ) {
          if (e.tag === 5) {
            var f = e.stateNode;
            c && d && (f = Eb(f, e.type, e.memoizedProps, e));
            Ka(a, f);
          } else if (e.tag === 6)
            f = e.stateNode, c && d && (f = Fb(f, e.memoizedProps, e)), Ka(a, f);
          else if (e.tag !== 4) {
            if (e.tag === 22 && e.memoizedState !== null)
              f = e.child, f !== null && (f.return = e), vg(a, e, true, true);
            else if (e.child !== null) {
              e.child.return = e;
              e = e.child;
              continue;
            }
          }
          if (e === b)
            break;
          for (;e.sibling === null; ) {
            if (e.return === null || e.return === b)
              return;
            e = e.return;
          }
          e.sibling.return = e.return;
          e = e.sibling;
        }
      };
      var zg = function(a, b, c, d) {
        for (var e = b.child;e !== null; ) {
          if (e.tag === 5) {
            var f = e.stateNode;
            c && d && (f = Eb(f, e.type, e.memoizedProps, e));
            Ab(a, f);
          } else if (e.tag === 6)
            f = e.stateNode, c && d && (f = Fb(f, e.memoizedProps, e)), Ab(a, f);
          else if (e.tag !== 4) {
            if (e.tag === 22 && e.memoizedState !== null)
              f = e.child, f !== null && (f.return = e), zg(a, e, true, true);
            else if (e.child !== null) {
              e.child.return = e;
              e = e.child;
              continue;
            }
          }
          if (e === b)
            break;
          for (;e.sibling === null; ) {
            if (e.return === null || e.return === b)
              return;
            e = e.return;
          }
          e.sibling.return = e.return;
          e = e.sibling;
        }
      };
      wg = function(a, b) {
        var c = b.stateNode;
        if (!ug(a, b)) {
          a = c.containerInfo;
          var d = zb(a);
          zg(d, b, false, false);
          c.pendingChildren = d;
          tg(b);
          Bb(a, d);
        }
      };
      xg = function(a, b, c, d, e) {
        var { stateNode: f, memoizedProps: g } = a;
        if ((a = ug(a, b)) && g === d)
          b.stateNode = f;
        else {
          var h = b.stateNode, k = re(oe.current), l = null;
          g !== d && (l = Ma(h, c, g, d, e, k));
          a && l === null ? b.stateNode = f : (f = yb(f, l, c, g, d, b, a, h), La(f, c, d, e, k) && tg(b), b.stateNode = f, a ? tg(b) : vg(f, b, false, false));
        }
      };
      yg = function(a, b, c, d) {
        c !== d ? (a = re(qe.current), c = re(oe.current), b.stateNode = Oa(d, a, c, b), tg(b)) : b.stateNode = a.stateNode;
      };
    } else
      wg = function() {}, xg = function() {}, yg = function() {};
    function Ag(a, b) {
      if (!F)
        switch (a.tailMode) {
          case "hidden":
            b = a.tail;
            for (var c = null;b !== null; )
              b.alternate !== null && (c = b), b = b.sibling;
            c === null ? a.tail = null : c.sibling = null;
            break;
          case "collapsed":
            c = a.tail;
            for (var d = null;c !== null; )
              c.alternate !== null && (d = c), c = c.sibling;
            d === null ? b || a.tail === null ? a.tail = null : a.tail.sibling = null : d.sibling = null;
        }
    }
    function Q(a) {
      var b = a.alternate !== null && a.alternate.child === a.child, c = 0, d = 0;
      if (b)
        for (var e = a.child;e !== null; )
          c |= e.lanes | e.childLanes, d |= e.subtreeFlags & 14680064, d |= e.flags & 14680064, e.return = a, e = e.sibling;
      else
        for (e = a.child;e !== null; )
          c |= e.lanes | e.childLanes, d |= e.subtreeFlags, d |= e.flags, e.return = a, e = e.sibling;
      a.subtreeFlags |= d;
      a.childLanes = c;
      return b;
    }
    function Bg(a, b, c) {
      var d = b.pendingProps;
      nd(b);
      switch (b.tag) {
        case 2:
        case 16:
        case 15:
        case 0:
        case 11:
        case 7:
        case 8:
        case 12:
        case 9:
        case 14:
          return Q(b), null;
        case 1:
          return A(b.type) && nc(), Q(b), null;
        case 3:
          c = b.stateNode;
          te();
          q(z);
          q(x);
          ye();
          c.pendingContext && (c.context = c.pendingContext, c.pendingContext = null);
          if (a === null || a.child === null)
            yd(b) ? tg(b) : a === null || a.memoizedState.isDehydrated && (b.flags & 256) === 0 || (b.flags |= 1024, rd !== null && (Cg(rd), rd = null));
          wg(a, b);
          Q(b);
          return null;
        case 5:
          ve(b);
          c = re(qe.current);
          var e = b.type;
          if (a !== null && b.stateNode != null)
            xg(a, b, e, d, c), a.ref !== b.ref && (b.flags |= 512, b.flags |= 2097152);
          else {
            if (!d) {
              if (b.stateNode === null)
                throw Error(n(166));
              Q(b);
              return null;
            }
            a = re(oe.current);
            if (yd(b)) {
              if (!Va)
                throw Error(n(175));
              a = Rb(b.stateNode, b.type, b.memoizedProps, c, a, b, !qd);
              b.updateQueue = a;
              a !== null && tg(b);
            } else {
              var f = Ja(e, d, c, a, b);
              vg(f, b, false, false);
              b.stateNode = f;
              La(f, e, d, c, a) && tg(b);
            }
            b.ref !== null && (b.flags |= 512, b.flags |= 2097152);
          }
          Q(b);
          return null;
        case 6:
          if (a && b.stateNode != null)
            yg(a, b, a.memoizedProps, d);
          else {
            if (typeof d !== "string" && b.stateNode === null)
              throw Error(n(166));
            a = re(qe.current);
            c = re(oe.current);
            if (yd(b)) {
              if (!Va)
                throw Error(n(176));
              a = b.stateNode;
              c = b.memoizedProps;
              if (d = Sb(a, c, b, !qd)) {
                if (e = od, e !== null)
                  switch (e.tag) {
                    case 3:
                      $b(e.stateNode.containerInfo, a, c, (e.mode & 1) !== 0);
                      break;
                    case 5:
                      ac(e.type, e.memoizedProps, e.stateNode, a, c, (e.mode & 1) !== 0);
                  }
              }
              d && tg(b);
            } else
              b.stateNode = Oa(d, a, c, b);
          }
          Q(b);
          return null;
        case 13:
          q(I);
          d = b.memoizedState;
          if (a === null || a.memoizedState !== null && a.memoizedState.dehydrated !== null) {
            if (F && pd !== null && (b.mode & 1) !== 0 && (b.flags & 128) === 0)
              zd(), Ad(), b.flags |= 98560, e = false;
            else if (e = yd(b), d !== null && d.dehydrated !== null) {
              if (a === null) {
                if (!e)
                  throw Error(n(318));
                if (!Va)
                  throw Error(n(344));
                e = b.memoizedState;
                e = e !== null ? e.dehydrated : null;
                if (!e)
                  throw Error(n(317));
                Tb(e, b);
              } else
                Ad(), (b.flags & 128) === 0 && (b.memoizedState = null), b.flags |= 4;
              Q(b);
              e = false;
            } else
              rd !== null && (Cg(rd), rd = null), e = true;
            if (!e)
              return b.flags & 65536 ? b : null;
          }
          if ((b.flags & 128) !== 0)
            return b.lanes = c, b;
          c = d !== null;
          c !== (a !== null && a.memoizedState !== null) && c && (b.child.flags |= 8192, (b.mode & 1) !== 0 && (a === null || (I.current & 1) !== 0 ? R === 0 && (R = 3) : ng()));
          b.updateQueue !== null && (b.flags |= 4);
          Q(b);
          return null;
        case 4:
          return te(), wg(a, b), a === null && Xa(b.stateNode.containerInfo), Q(b), null;
        case 10:
          return Wd(b.type._context), Q(b), null;
        case 17:
          return A(b.type) && nc(), Q(b), null;
        case 19:
          q(I);
          e = b.memoizedState;
          if (e === null)
            return Q(b), null;
          d = (b.flags & 128) !== 0;
          f = e.rendering;
          if (f === null)
            if (d)
              Ag(e, false);
            else {
              if (R !== 0 || a !== null && (a.flags & 128) !== 0)
                for (a = b.child;a !== null; ) {
                  f = we(a);
                  if (f !== null) {
                    b.flags |= 128;
                    Ag(e, false);
                    a = f.updateQueue;
                    a !== null && (b.updateQueue = a, b.flags |= 4);
                    b.subtreeFlags = 0;
                    a = c;
                    for (c = b.child;c !== null; )
                      d = c, e = a, d.flags &= 14680066, f = d.alternate, f === null ? (d.childLanes = 0, d.lanes = e, d.child = null, d.subtreeFlags = 0, d.memoizedProps = null, d.memoizedState = null, d.updateQueue = null, d.dependencies = null, d.stateNode = null) : (d.childLanes = f.childLanes, d.lanes = f.lanes, d.child = f.child, d.subtreeFlags = 0, d.deletions = null, d.memoizedProps = f.memoizedProps, d.memoizedState = f.memoizedState, d.updateQueue = f.updateQueue, d.type = f.type, e = f.dependencies, d.dependencies = e === null ? null : { lanes: e.lanes, firstContext: e.firstContext }), c = c.sibling;
                    v(I, I.current & 1 | 2);
                    return b.child;
                  }
                  a = a.sibling;
                }
              e.tail !== null && D() > Dg && (b.flags |= 128, d = true, Ag(e, false), b.lanes = 4194304);
            }
          else {
            if (!d)
              if (a = we(f), a !== null) {
                if (b.flags |= 128, d = true, a = a.updateQueue, a !== null && (b.updateQueue = a, b.flags |= 4), Ag(e, true), e.tail === null && e.tailMode === "hidden" && !f.alternate && !F)
                  return Q(b), null;
              } else
                2 * D() - e.renderingStartTime > Dg && c !== 1073741824 && (b.flags |= 128, d = true, Ag(e, false), b.lanes = 4194304);
            e.isBackwards ? (f.sibling = b.child, b.child = f) : (a = e.last, a !== null ? a.sibling = f : b.child = f, e.last = f);
          }
          if (e.tail !== null)
            return b = e.tail, e.rendering = b, e.tail = b.sibling, e.renderingStartTime = D(), b.sibling = null, a = I.current, v(I, d ? a & 1 | 2 : a & 1), b;
          Q(b);
          return null;
        case 22:
        case 23:
          return Eg(), c = b.memoizedState !== null, a !== null && a.memoizedState !== null !== c && (b.flags |= 8192), c && (b.mode & 1) !== 0 ? ($f & 1073741824) !== 0 && (Q(b), Ta && b.subtreeFlags & 6 && (b.flags |= 8192)) : Q(b), null;
        case 24:
          return null;
        case 25:
          return null;
      }
      throw Error(n(156, b.tag));
    }
    function Fg(a, b) {
      nd(b);
      switch (b.tag) {
        case 1:
          return A(b.type) && nc(), a = b.flags, a & 65536 ? (b.flags = a & -65537 | 128, b) : null;
        case 3:
          return te(), q(z), q(x), ye(), a = b.flags, (a & 65536) !== 0 && (a & 128) === 0 ? (b.flags = a & -65537 | 128, b) : null;
        case 5:
          return ve(b), null;
        case 13:
          q(I);
          a = b.memoizedState;
          if (a !== null && a.dehydrated !== null) {
            if (b.alternate === null)
              throw Error(n(340));
            Ad();
          }
          a = b.flags;
          return a & 65536 ? (b.flags = a & -65537 | 128, b) : null;
        case 19:
          return q(I), null;
        case 4:
          return te(), null;
        case 10:
          return Wd(b.type._context), null;
        case 22:
        case 23:
          return Eg(), null;
        case 24:
          return null;
        default:
          return null;
      }
    }
    var Gg = false, S = false, Hg = typeof WeakSet === "function" ? WeakSet : Set, T = null;
    function Ig(a, b) {
      var c = a.ref;
      if (c !== null)
        if (typeof c === "function")
          try {
            c(null);
          } catch (d) {
            U(a, b, d);
          }
        else
          c.current = null;
    }
    function Jg(a, b, c) {
      try {
        c();
      } catch (d) {
        U(a, b, d);
      }
    }
    var Kg = false;
    function Lg(a, b) {
      Ha(a.containerInfo);
      for (T = b;T !== null; )
        if (a = T, b = a.child, (a.subtreeFlags & 1028) !== 0 && b !== null)
          b.return = a, T = b;
        else
          for (;T !== null; ) {
            a = T;
            try {
              var c = a.alternate;
              if ((a.flags & 1024) !== 0)
                switch (a.tag) {
                  case 0:
                  case 11:
                  case 15:
                    break;
                  case 1:
                    if (c !== null) {
                      var { memoizedProps: d, memoizedState: e } = c, f = a.stateNode, g = f.getSnapshotBeforeUpdate(a.elementType === a.type ? d : xf(a.type, d), e);
                      f.__reactInternalSnapshotBeforeUpdate = g;
                    }
                    break;
                  case 3:
                    Ta && xb(a.stateNode.containerInfo);
                    break;
                  case 5:
                  case 6:
                  case 4:
                  case 17:
                    break;
                  default:
                    throw Error(n(163));
                }
            } catch (h) {
              U(a, a.return, h);
            }
            b = a.sibling;
            if (b !== null) {
              b.return = a.return;
              T = b;
              break;
            }
            T = a.return;
          }
      c = Kg;
      Kg = false;
      return c;
    }
    function Mg(a, b, c) {
      var d = b.updateQueue;
      d = d !== null ? d.lastEffect : null;
      if (d !== null) {
        var e = d = d.next;
        do {
          if ((e.tag & a) === a) {
            var f = e.destroy;
            e.destroy = undefined;
            f !== undefined && Jg(b, c, f);
          }
          e = e.next;
        } while (e !== d);
      }
    }
    function Ng(a, b) {
      b = b.updateQueue;
      b = b !== null ? b.lastEffect : null;
      if (b !== null) {
        var c = b = b.next;
        do {
          if ((c.tag & a) === a) {
            var d = c.create;
            c.destroy = d();
          }
          c = c.next;
        } while (c !== b);
      }
    }
    function Og(a) {
      var b = a.ref;
      if (b !== null) {
        var c = a.stateNode;
        switch (a.tag) {
          case 5:
            a = Ea(c);
            break;
          default:
            a = c;
        }
        typeof b === "function" ? b(a) : b.current = a;
      }
    }
    function Pg(a) {
      var b = a.alternate;
      b !== null && (a.alternate = null, Pg(b));
      a.child = null;
      a.deletions = null;
      a.sibling = null;
      a.tag === 5 && (b = a.stateNode, b !== null && Za(b));
      a.stateNode = null;
      a.return = null;
      a.dependencies = null;
      a.memoizedProps = null;
      a.memoizedState = null;
      a.pendingProps = null;
      a.stateNode = null;
      a.updateQueue = null;
    }
    function Qg(a) {
      return a.tag === 5 || a.tag === 3 || a.tag === 4;
    }
    function Rg(a) {
      a:
        for (;; ) {
          for (;a.sibling === null; ) {
            if (a.return === null || Qg(a.return))
              return null;
            a = a.return;
          }
          a.sibling.return = a.return;
          for (a = a.sibling;a.tag !== 5 && a.tag !== 6 && a.tag !== 18; ) {
            if (a.flags & 2)
              continue a;
            if (a.child === null || a.tag === 4)
              continue a;
            else
              a.child.return = a, a = a.child;
          }
          if (!(a.flags & 2))
            return a.stateNode;
        }
    }
    function Sg(a, b, c) {
      var d = a.tag;
      if (d === 5 || d === 6)
        a = a.stateNode, b ? pb(c, a, b) : kb(c, a);
      else if (d !== 4 && (a = a.child, a !== null))
        for (Sg(a, b, c), a = a.sibling;a !== null; )
          Sg(a, b, c), a = a.sibling;
    }
    function Tg(a, b, c) {
      var d = a.tag;
      if (d === 5 || d === 6)
        a = a.stateNode, b ? ob(c, a, b) : jb(c, a);
      else if (d !== 4 && (a = a.child, a !== null))
        for (Tg(a, b, c), a = a.sibling;a !== null; )
          Tg(a, b, c), a = a.sibling;
    }
    var V = null, Ug = false;
    function Vg(a, b, c) {
      for (c = c.child;c !== null; )
        Wg(a, b, c), c = c.sibling;
    }
    function Wg(a, b, c) {
      if (Sc && typeof Sc.onCommitFiberUnmount === "function")
        try {
          Sc.onCommitFiberUnmount(Rc, c);
        } catch (h) {}
      switch (c.tag) {
        case 5:
          S || Ig(c, b);
        case 6:
          if (Ta) {
            var d = V, e = Ug;
            V = null;
            Vg(a, b, c);
            V = d;
            Ug = e;
            V !== null && (Ug ? rb(V, c.stateNode) : qb(V, c.stateNode));
          } else
            Vg(a, b, c);
          break;
        case 18:
          Ta && V !== null && (Ug ? Yb(V, c.stateNode) : Xb(V, c.stateNode));
          break;
        case 4:
          Ta ? (d = V, e = Ug, V = c.stateNode.containerInfo, Ug = true, Vg(a, b, c), V = d, Ug = e) : (Ua && (d = c.stateNode.containerInfo, e = zb(d), Cb(d, e)), Vg(a, b, c));
          break;
        case 0:
        case 11:
        case 14:
        case 15:
          if (!S && (d = c.updateQueue, d !== null && (d = d.lastEffect, d !== null))) {
            e = d = d.next;
            do {
              var f = e, g = f.destroy;
              f = f.tag;
              g !== undefined && ((f & 2) !== 0 ? Jg(c, b, g) : (f & 4) !== 0 && Jg(c, b, g));
              e = e.next;
            } while (e !== d);
          }
          Vg(a, b, c);
          break;
        case 1:
          if (!S && (Ig(c, b), d = c.stateNode, typeof d.componentWillUnmount === "function"))
            try {
              d.props = c.memoizedProps, d.state = c.memoizedState, d.componentWillUnmount();
            } catch (h) {
              U(c, b, h);
            }
          Vg(a, b, c);
          break;
        case 21:
          Vg(a, b, c);
          break;
        case 22:
          c.mode & 1 ? (S = (d = S) || c.memoizedState !== null, Vg(a, b, c), S = d) : Vg(a, b, c);
          break;
        default:
          Vg(a, b, c);
      }
    }
    function Xg(a) {
      var b = a.updateQueue;
      if (b !== null) {
        a.updateQueue = null;
        var c = a.stateNode;
        c === null && (c = a.stateNode = new Hg);
        b.forEach(function(b2) {
          var d = Yg.bind(null, a, b2);
          c.has(b2) || (c.add(b2), b2.then(d, d));
        });
      }
    }
    function Zg(a, b) {
      var c = b.deletions;
      if (c !== null)
        for (var d = 0;d < c.length; d++) {
          var e = c[d];
          try {
            var f = a, g = b;
            if (Ta) {
              var h = g;
              a:
                for (;h !== null; ) {
                  switch (h.tag) {
                    case 5:
                      V = h.stateNode;
                      Ug = false;
                      break a;
                    case 3:
                      V = h.stateNode.containerInfo;
                      Ug = true;
                      break a;
                    case 4:
                      V = h.stateNode.containerInfo;
                      Ug = true;
                      break a;
                  }
                  h = h.return;
                }
              if (V === null)
                throw Error(n(160));
              Wg(f, g, e);
              V = null;
              Ug = false;
            } else
              Wg(f, g, e);
            var k = e.alternate;
            k !== null && (k.return = null);
            e.return = null;
          } catch (l) {
            U(e, b, l);
          }
        }
      if (b.subtreeFlags & 12854)
        for (b = b.child;b !== null; )
          $g(b, a), b = b.sibling;
    }
    function $g(a, b) {
      var { alternate: c, flags: d } = a;
      switch (a.tag) {
        case 0:
        case 11:
        case 14:
        case 15:
          Zg(b, a);
          ah(a);
          if (d & 4) {
            try {
              Mg(3, a, a.return), Ng(3, a);
            } catch (p) {
              U(a, a.return, p);
            }
            try {
              Mg(5, a, a.return);
            } catch (p) {
              U(a, a.return, p);
            }
          }
          break;
        case 1:
          Zg(b, a);
          ah(a);
          d & 512 && c !== null && Ig(c, c.return);
          break;
        case 5:
          Zg(b, a);
          ah(a);
          d & 512 && c !== null && Ig(c, c.return);
          if (Ta) {
            if (a.flags & 32) {
              var e = a.stateNode;
              try {
                sb(e);
              } catch (p) {
                U(a, a.return, p);
              }
            }
            if (d & 4 && (e = a.stateNode, e != null)) {
              var f = a.memoizedProps;
              c = c !== null ? c.memoizedProps : f;
              d = a.type;
              b = a.updateQueue;
              a.updateQueue = null;
              if (b !== null)
                try {
                  nb(e, b, d, c, f, a);
                } catch (p) {
                  U(a, a.return, p);
                }
            }
          }
          break;
        case 6:
          Zg(b, a);
          ah(a);
          if (d & 4 && Ta) {
            if (a.stateNode === null)
              throw Error(n(162));
            e = a.stateNode;
            f = a.memoizedProps;
            c = c !== null ? c.memoizedProps : f;
            try {
              lb(e, c, f);
            } catch (p) {
              U(a, a.return, p);
            }
          }
          break;
        case 3:
          Zg(b, a);
          ah(a);
          if (d & 4) {
            if (Ta && Va && c !== null && c.memoizedState.isDehydrated)
              try {
                Vb(b.containerInfo);
              } catch (p) {
                U(a, a.return, p);
              }
            if (Ua) {
              e = b.containerInfo;
              f = b.pendingChildren;
              try {
                Cb(e, f);
              } catch (p) {
                U(a, a.return, p);
              }
            }
          }
          break;
        case 4:
          Zg(b, a);
          ah(a);
          if (d & 4 && Ua) {
            f = a.stateNode;
            e = f.containerInfo;
            f = f.pendingChildren;
            try {
              Cb(e, f);
            } catch (p) {
              U(a, a.return, p);
            }
          }
          break;
        case 13:
          Zg(b, a);
          ah(a);
          e = a.child;
          e.flags & 8192 && (f = e.memoizedState !== null, e.stateNode.isHidden = f, !f || e.alternate !== null && e.alternate.memoizedState !== null || (bh = D()));
          d & 4 && Xg(a);
          break;
        case 22:
          var g = c !== null && c.memoizedState !== null;
          a.mode & 1 ? (S = (c = S) || g, Zg(b, a), S = c) : Zg(b, a);
          ah(a);
          if (d & 8192) {
            c = a.memoizedState !== null;
            if ((a.stateNode.isHidden = c) && !g && (a.mode & 1) !== 0)
              for (T = a, d = a.child;d !== null; ) {
                for (b = T = d;T !== null; ) {
                  g = T;
                  var h = g.child;
                  switch (g.tag) {
                    case 0:
                    case 11:
                    case 14:
                    case 15:
                      Mg(4, g, g.return);
                      break;
                    case 1:
                      Ig(g, g.return);
                      var k = g.stateNode;
                      if (typeof k.componentWillUnmount === "function") {
                        var l = g, m = g.return;
                        try {
                          var r = l;
                          k.props = r.memoizedProps;
                          k.state = r.memoizedState;
                          k.componentWillUnmount();
                        } catch (p) {
                          U(l, m, p);
                        }
                      }
                      break;
                    case 5:
                      Ig(g, g.return);
                      break;
                    case 22:
                      if (g.memoizedState !== null) {
                        ch(b);
                        continue;
                      }
                  }
                  h !== null ? (h.return = g, T = h) : ch(b);
                }
                d = d.sibling;
              }
            if (Ta)
              a:
                if (d = null, Ta)
                  for (b = a;; ) {
                    if (b.tag === 5) {
                      if (d === null) {
                        d = b;
                        try {
                          e = b.stateNode, c ? tb(e) : vb(b.stateNode, b.memoizedProps);
                        } catch (p) {
                          U(a, a.return, p);
                        }
                      }
                    } else if (b.tag === 6) {
                      if (d === null)
                        try {
                          f = b.stateNode, c ? ub(f) : wb(f, b.memoizedProps);
                        } catch (p) {
                          U(a, a.return, p);
                        }
                    } else if ((b.tag !== 22 && b.tag !== 23 || b.memoizedState === null || b === a) && b.child !== null) {
                      b.child.return = b;
                      b = b.child;
                      continue;
                    }
                    if (b === a)
                      break a;
                    for (;b.sibling === null; ) {
                      if (b.return === null || b.return === a)
                        break a;
                      d === b && (d = null);
                      b = b.return;
                    }
                    d === b && (d = null);
                    b.sibling.return = b.return;
                    b = b.sibling;
                  }
          }
          break;
        case 19:
          Zg(b, a);
          ah(a);
          d & 4 && Xg(a);
          break;
        case 21:
          break;
        default:
          Zg(b, a), ah(a);
      }
    }
    function ah(a) {
      var b = a.flags;
      if (b & 2) {
        try {
          if (Ta) {
            b: {
              for (var c = a.return;c !== null; ) {
                if (Qg(c)) {
                  var d = c;
                  break b;
                }
                c = c.return;
              }
              throw Error(n(160));
            }
            switch (d.tag) {
              case 5:
                var e = d.stateNode;
                d.flags & 32 && (sb(e), d.flags &= -33);
                var f = Rg(a);
                Tg(a, f, e);
                break;
              case 3:
              case 4:
                var g = d.stateNode.containerInfo, h = Rg(a);
                Sg(a, h, g);
                break;
              default:
                throw Error(n(161));
            }
          }
        } catch (k) {
          U(a, a.return, k);
        }
        a.flags &= -3;
      }
      b & 4096 && (a.flags &= -4097);
    }
    function dh(a, b, c) {
      T = a;
      eh(a, b, c);
    }
    function eh(a, b, c) {
      for (var d = (a.mode & 1) !== 0;T !== null; ) {
        var e = T, f = e.child;
        if (e.tag === 22 && d) {
          var g = e.memoizedState !== null || Gg;
          if (!g) {
            var h = e.alternate, k = h !== null && h.memoizedState !== null || S;
            h = Gg;
            var l = S;
            Gg = g;
            if ((S = k) && !l)
              for (T = e;T !== null; )
                g = T, k = g.child, g.tag === 22 && g.memoizedState !== null ? fh(e) : k !== null ? (k.return = g, T = k) : fh(e);
            for (;f !== null; )
              T = f, eh(f, b, c), f = f.sibling;
            T = e;
            Gg = h;
            S = l;
          }
          gh(a, b, c);
        } else
          (e.subtreeFlags & 8772) !== 0 && f !== null ? (f.return = e, T = f) : gh(a, b, c);
      }
    }
    function gh(a) {
      for (;T !== null; ) {
        var b = T;
        if ((b.flags & 8772) !== 0) {
          var c = b.alternate;
          try {
            if ((b.flags & 8772) !== 0)
              switch (b.tag) {
                case 0:
                case 11:
                case 15:
                  S || Ng(5, b);
                  break;
                case 1:
                  var d = b.stateNode;
                  if (b.flags & 4 && !S)
                    if (c === null)
                      d.componentDidMount();
                    else {
                      var e = b.elementType === b.type ? c.memoizedProps : xf(b.type, c.memoizedProps);
                      d.componentDidUpdate(e, c.memoizedState, d.__reactInternalSnapshotBeforeUpdate);
                    }
                  var f = b.updateQueue;
                  f !== null && me(b, f, d);
                  break;
                case 3:
                  var g = b.updateQueue;
                  if (g !== null) {
                    c = null;
                    if (b.child !== null)
                      switch (b.child.tag) {
                        case 5:
                          c = Ea(b.child.stateNode);
                          break;
                        case 1:
                          c = b.child.stateNode;
                      }
                    me(b, g, c);
                  }
                  break;
                case 5:
                  var h = b.stateNode;
                  c === null && b.flags & 4 && mb(h, b.type, b.memoizedProps, b);
                  break;
                case 6:
                  break;
                case 4:
                  break;
                case 12:
                  break;
                case 13:
                  if (Va && b.memoizedState === null) {
                    var k = b.alternate;
                    if (k !== null) {
                      var l = k.memoizedState;
                      if (l !== null) {
                        var m = l.dehydrated;
                        m !== null && Wb(m);
                      }
                    }
                  }
                  break;
                case 19:
                case 17:
                case 21:
                case 22:
                case 23:
                case 25:
                  break;
                default:
                  throw Error(n(163));
              }
            S || b.flags & 512 && Og(b);
          } catch (r) {
            U(b, b.return, r);
          }
        }
        if (b === a) {
          T = null;
          break;
        }
        c = b.sibling;
        if (c !== null) {
          c.return = b.return;
          T = c;
          break;
        }
        T = b.return;
      }
    }
    function ch(a) {
      for (;T !== null; ) {
        var b = T;
        if (b === a) {
          T = null;
          break;
        }
        var c = b.sibling;
        if (c !== null) {
          c.return = b.return;
          T = c;
          break;
        }
        T = b.return;
      }
    }
    function fh(a) {
      for (;T !== null; ) {
        var b = T;
        try {
          switch (b.tag) {
            case 0:
            case 11:
            case 15:
              var c = b.return;
              try {
                Ng(4, b);
              } catch (k) {
                U(b, c, k);
              }
              break;
            case 1:
              var d = b.stateNode;
              if (typeof d.componentDidMount === "function") {
                var e = b.return;
                try {
                  d.componentDidMount();
                } catch (k) {
                  U(b, e, k);
                }
              }
              var f = b.return;
              try {
                Og(b);
              } catch (k) {
                U(b, f, k);
              }
              break;
            case 5:
              var g = b.return;
              try {
                Og(b);
              } catch (k) {
                U(b, g, k);
              }
          }
        } catch (k) {
          U(b, b.return, k);
        }
        if (b === a) {
          T = null;
          break;
        }
        var h = b.sibling;
        if (h !== null) {
          h.return = b.return;
          T = h;
          break;
        }
        T = b.return;
      }
    }
    var hh = 0, ih = 1, jh = 2, kh = 3, lh = 4;
    if (typeof Symbol === "function" && Symbol.for) {
      var mh = Symbol.for;
      hh = mh("selector.component");
      ih = mh("selector.has_pseudo_class");
      jh = mh("selector.role");
      kh = mh("selector.test_id");
      lh = mh("selector.text");
    }
    function nh(a) {
      var b = Wa(a);
      if (b != null) {
        if (typeof b.memoizedProps["data-testname"] !== "string")
          throw Error(n(364));
        return b;
      }
      a = cb(a);
      if (a === null)
        throw Error(n(362));
      return a.stateNode.current;
    }
    function oh(a, b) {
      switch (b.$$typeof) {
        case hh:
          if (a.type === b.value)
            return true;
          break;
        case ih:
          a: {
            b = b.value;
            a = [a, 0];
            for (var c = 0;c < a.length; ) {
              var d = a[c++], e = a[c++], f = b[e];
              if (d.tag !== 5 || !fb(d)) {
                for (;f != null && oh(d, f); )
                  e++, f = b[e];
                if (e === b.length) {
                  b = true;
                  break a;
                } else
                  for (d = d.child;d !== null; )
                    a.push(d, e), d = d.sibling;
              }
            }
            b = false;
          }
          return b;
        case jh:
          if (a.tag === 5 && gb(a.stateNode, b.value))
            return true;
          break;
        case lh:
          if (a.tag === 5 || a.tag === 6) {
            if (a = eb(a), a !== null && 0 <= a.indexOf(b.value))
              return true;
          }
          break;
        case kh:
          if (a.tag === 5 && (a = a.memoizedProps["data-testname"], typeof a === "string" && a.toLowerCase() === b.value.toLowerCase()))
            return true;
          break;
        default:
          throw Error(n(365));
      }
      return false;
    }
    function ph(a) {
      switch (a.$$typeof) {
        case hh:
          return "<" + (ua(a.value) || "Unknown") + ">";
        case ih:
          return ":has(" + (ph(a) || "") + ")";
        case jh:
          return '[role="' + a.value + '"]';
        case lh:
          return '"' + a.value + '"';
        case kh:
          return '[data-testname="' + a.value + '"]';
        default:
          throw Error(n(365));
      }
    }
    function qh(a, b) {
      var c = [];
      a = [a, 0];
      for (var d = 0;d < a.length; ) {
        var e = a[d++], f = a[d++], g = b[f];
        if (e.tag !== 5 || !fb(e)) {
          for (;g != null && oh(e, g); )
            f++, g = b[f];
          if (f === b.length)
            c.push(e);
          else
            for (e = e.child;e !== null; )
              a.push(e, f), e = e.sibling;
        }
      }
      return c;
    }
    function rh(a, b) {
      if (!bb)
        throw Error(n(363));
      a = nh(a);
      a = qh(a, b);
      b = [];
      a = Array.from(a);
      for (var c = 0;c < a.length; ) {
        var d = a[c++];
        if (d.tag === 5)
          fb(d) || b.push(d.stateNode);
        else
          for (d = d.child;d !== null; )
            a.push(d), d = d.sibling;
      }
      return b;
    }
    var sh = Math.ceil, th = da.ReactCurrentDispatcher, uh = da.ReactCurrentOwner, W = da.ReactCurrentBatchConfig, H = 0, N = null, X = null, Z = 0, $f = 0, Zf = ic(0), R = 0, vh = null, le = 0, wh = 0, xh = 0, yh = null, zh = null, bh = 0, Dg = Infinity, Ah = null;
    function Bh() {
      Dg = D() + 500;
    }
    var Jf = false, Kf = null, Mf = null, Ch = false, Dh = null, Eh = 0, Fh = 0, Gh = null, Hh = -1, Ih = 0;
    function O() {
      return (H & 6) !== 0 ? D() : Hh !== -1 ? Hh : Hh = D();
    }
    function tf(a) {
      if ((a.mode & 1) === 0)
        return 1;
      if ((H & 2) !== 0 && Z !== 0)
        return Z & -Z;
      if (Cd.transition !== null)
        return Ih === 0 && (Ih = Dc()), Ih;
      a = C;
      return a !== 0 ? a : Ya();
    }
    function af(a, b, c, d) {
      if (50 < Fh)
        throw Fh = 0, Gh = null, Error(n(185));
      Fc(a, c, d);
      if ((H & 2) === 0 || a !== N)
        a === N && ((H & 2) === 0 && (wh |= c), R === 4 && Jh(a, Z)), Kh(a, d), c === 1 && H === 0 && (b.mode & 1) === 0 && (Bh(), Xc && ad());
    }
    function Kh(a, b) {
      var c = a.callbackNode;
      Bc(a, b);
      var d = zc(a, a === N ? Z : 0);
      if (d === 0)
        c !== null && Kc(c), a.callbackNode = null, a.callbackPriority = 0;
      else if (b = d & -d, a.callbackPriority !== b) {
        c != null && Kc(c);
        if (b === 1)
          a.tag === 0 ? $c(Lh.bind(null, a)) : Zc(Lh.bind(null, a)), $a ? ab(function() {
            (H & 6) === 0 && ad();
          }) : Jc(Nc, ad), c = null;
        else {
          switch (Ic(d)) {
            case 1:
              c = Nc;
              break;
            case 4:
              c = Oc;
              break;
            case 16:
              c = Pc;
              break;
            case 536870912:
              c = Qc;
              break;
            default:
              c = Pc;
          }
          c = Mh(c, Nh.bind(null, a));
        }
        a.callbackPriority = b;
        a.callbackNode = c;
      }
    }
    function Nh(a, b) {
      Hh = -1;
      Ih = 0;
      if ((H & 6) !== 0)
        throw Error(n(327));
      var c = a.callbackNode;
      if (Oh() && a.callbackNode !== c)
        return null;
      var d = zc(a, a === N ? Z : 0);
      if (d === 0)
        return null;
      if ((d & 30) !== 0 || (d & a.expiredLanes) !== 0 || b)
        b = Ph(a, d);
      else {
        b = d;
        var e = H;
        H |= 2;
        var f = Qh();
        if (N !== a || Z !== b)
          Ah = null, Bh(), Rh(a, b);
        do
          try {
            Sh();
            break;
          } catch (h) {
            Th(a, h);
          }
        while (1);
        Ud();
        th.current = f;
        H = e;
        X !== null ? b = 0 : (N = null, Z = 0, b = R);
      }
      if (b !== 0) {
        b === 2 && (e = Cc(a), e !== 0 && (d = e, b = Uh(a, e)));
        if (b === 1)
          throw c = vh, Rh(a, 0), Jh(a, d), Kh(a, D()), c;
        if (b === 6)
          Jh(a, d);
        else {
          e = a.current.alternate;
          if ((d & 30) === 0 && !Vh(e) && (b = Ph(a, d), b === 2 && (f = Cc(a), f !== 0 && (d = f, b = Uh(a, f))), b === 1))
            throw c = vh, Rh(a, 0), Jh(a, d), Kh(a, D()), c;
          a.finishedWork = e;
          a.finishedLanes = d;
          switch (b) {
            case 0:
            case 1:
              throw Error(n(345));
            case 2:
              Wh(a, zh, Ah);
              break;
            case 3:
              Jh(a, d);
              if ((d & 130023424) === d && (b = bh + 500 - D(), 10 < b)) {
                if (zc(a, 0) !== 0)
                  break;
                e = a.suspendedLanes;
                if ((e & d) !== d) {
                  O();
                  a.pingedLanes |= a.suspendedLanes & e;
                  break;
                }
                a.timeoutHandle = Pa(Wh.bind(null, a, zh, Ah), b);
                break;
              }
              Wh(a, zh, Ah);
              break;
            case 4:
              Jh(a, d);
              if ((d & 4194240) === d)
                break;
              b = a.eventTimes;
              for (e = -1;0 < d; ) {
                var g = 31 - tc(d);
                f = 1 << g;
                g = b[g];
                g > e && (e = g);
                d &= ~f;
              }
              d = e;
              d = D() - d;
              d = (120 > d ? 120 : 480 > d ? 480 : 1080 > d ? 1080 : 1920 > d ? 1920 : 3000 > d ? 3000 : 4320 > d ? 4320 : 1960 * sh(d / 1960)) - d;
              if (10 < d) {
                a.timeoutHandle = Pa(Wh.bind(null, a, zh, Ah), d);
                break;
              }
              Wh(a, zh, Ah);
              break;
            case 5:
              Wh(a, zh, Ah);
              break;
            default:
              throw Error(n(329));
          }
        }
      }
      Kh(a, D());
      return a.callbackNode === c ? Nh.bind(null, a) : null;
    }
    function Uh(a, b) {
      var c = yh;
      a.current.memoizedState.isDehydrated && (Rh(a, b).flags |= 256);
      a = Ph(a, b);
      a !== 2 && (b = zh, zh = c, b !== null && Cg(b));
      return a;
    }
    function Cg(a) {
      zh === null ? zh = a : zh.push.apply(zh, a);
    }
    function Vh(a) {
      for (var b = a;; ) {
        if (b.flags & 16384) {
          var c = b.updateQueue;
          if (c !== null && (c = c.stores, c !== null))
            for (var d = 0;d < c.length; d++) {
              var e = c[d], f = e.getSnapshot;
              e = e.value;
              try {
                if (!Vc(f(), e))
                  return false;
              } catch (g) {
                return false;
              }
            }
        }
        c = b.child;
        if (b.subtreeFlags & 16384 && c !== null)
          c.return = b, b = c;
        else {
          if (b === a)
            break;
          for (;b.sibling === null; ) {
            if (b.return === null || b.return === a)
              return true;
            b = b.return;
          }
          b.sibling.return = b.return;
          b = b.sibling;
        }
      }
      return true;
    }
    function Jh(a, b) {
      b &= ~xh;
      b &= ~wh;
      a.suspendedLanes |= b;
      a.pingedLanes &= ~b;
      for (a = a.expirationTimes;0 < b; ) {
        var c = 31 - tc(b), d = 1 << c;
        a[c] = -1;
        b &= ~d;
      }
    }
    function Lh(a) {
      if ((H & 6) !== 0)
        throw Error(n(327));
      Oh();
      var b = zc(a, 0);
      if ((b & 1) === 0)
        return Kh(a, D()), null;
      var c = Ph(a, b);
      if (a.tag !== 0 && c === 2) {
        var d = Cc(a);
        d !== 0 && (b = d, c = Uh(a, d));
      }
      if (c === 1)
        throw c = vh, Rh(a, 0), Jh(a, b), Kh(a, D()), c;
      if (c === 6)
        throw Error(n(345));
      a.finishedWork = a.current.alternate;
      a.finishedLanes = b;
      Wh(a, zh, Ah);
      Kh(a, D());
      return null;
    }
    function Xh(a) {
      Dh !== null && Dh.tag === 0 && (H & 6) === 0 && Oh();
      var b = H;
      H |= 1;
      var c = W.transition, d = C;
      try {
        if (W.transition = null, C = 1, a)
          return a();
      } finally {
        C = d, W.transition = c, H = b, (H & 6) === 0 && ad();
      }
    }
    function Eg() {
      $f = Zf.current;
      q(Zf);
    }
    function Rh(a, b) {
      a.finishedWork = null;
      a.finishedLanes = 0;
      var c = a.timeoutHandle;
      c !== Ra && (a.timeoutHandle = Ra, Qa(c));
      if (X !== null)
        for (c = X.return;c !== null; ) {
          var d = c;
          nd(d);
          switch (d.tag) {
            case 1:
              d = d.type.childContextTypes;
              d !== null && d !== undefined && nc();
              break;
            case 3:
              te();
              q(z);
              q(x);
              ye();
              break;
            case 5:
              ve(d);
              break;
            case 4:
              te();
              break;
            case 13:
              q(I);
              break;
            case 19:
              q(I);
              break;
            case 10:
              Wd(d.type._context);
              break;
            case 22:
            case 23:
              Eg();
          }
          c = c.return;
        }
      N = a;
      X = a = Jd(a.current, null);
      Z = $f = b;
      R = 0;
      vh = null;
      xh = wh = le = 0;
      zh = yh = null;
      if ($d !== null) {
        for (b = 0;b < $d.length; b++)
          if (c = $d[b], d = c.interleaved, d !== null) {
            c.interleaved = null;
            var e = d.next, f = c.pending;
            if (f !== null) {
              var g = f.next;
              f.next = e;
              d.next = g;
            }
            c.pending = d;
          }
        $d = null;
      }
      return a;
    }
    function Th(a, b) {
      do {
        var c = X;
        try {
          Ud();
          ze.current = Le;
          if (Ce) {
            for (var d = J.memoizedState;d !== null; ) {
              var e = d.queue;
              e !== null && (e.pending = null);
              d = d.next;
            }
            Ce = false;
          }
          Be = 0;
          L = K = J = null;
          De = false;
          Ee = 0;
          uh.current = null;
          if (c === null || c.return === null) {
            R = 1;
            vh = b;
            X = null;
            break;
          }
          a: {
            var f = a, g = c.return, h = c, k = b;
            b = Z;
            h.flags |= 32768;
            if (k !== null && typeof k === "object" && typeof k.then === "function") {
              var l = k, m = h, r = m.tag;
              if ((m.mode & 1) === 0 && (r === 0 || r === 11 || r === 15)) {
                var p = m.alternate;
                p ? (m.updateQueue = p.updateQueue, m.memoizedState = p.memoizedState, m.lanes = p.lanes) : (m.updateQueue = null, m.memoizedState = null);
              }
              var B = Pf(g);
              if (B !== null) {
                B.flags &= -257;
                Qf(B, g, h, f, b);
                B.mode & 1 && Nf(f, l, b);
                b = B;
                k = l;
                var w = b.updateQueue;
                if (w === null) {
                  var Y = new Set;
                  Y.add(k);
                  b.updateQueue = Y;
                } else
                  w.add(k);
                break a;
              } else {
                if ((b & 1) === 0) {
                  Nf(f, l, b);
                  ng();
                  break a;
                }
                k = Error(n(426));
              }
            } else if (F && h.mode & 1) {
              var ya = Pf(g);
              if (ya !== null) {
                (ya.flags & 65536) === 0 && (ya.flags |= 256);
                Qf(ya, g, h, f, b);
                Bd(Ef(k, h));
                break a;
              }
            }
            f = k = Ef(k, h);
            R !== 4 && (R = 2);
            yh === null ? yh = [f] : yh.push(f);
            f = g;
            do {
              switch (f.tag) {
                case 3:
                  f.flags |= 65536;
                  b &= -b;
                  f.lanes |= b;
                  var E = If(f, k, b);
                  je(f, E);
                  break a;
                case 1:
                  h = k;
                  var { type: u, stateNode: t } = f;
                  if ((f.flags & 128) === 0 && (typeof u.getDerivedStateFromError === "function" || t !== null && typeof t.componentDidCatch === "function" && (Mf === null || !Mf.has(t)))) {
                    f.flags |= 65536;
                    b &= -b;
                    f.lanes |= b;
                    var Db = Lf(f, h, b);
                    je(f, Db);
                    break a;
                  }
              }
              f = f.return;
            } while (f !== null);
          }
          Yh(c);
        } catch (lc) {
          b = lc;
          X === c && c !== null && (X = c = c.return);
          continue;
        }
        break;
      } while (1);
    }
    function Qh() {
      var a = th.current;
      th.current = Le;
      return a === null ? Le : a;
    }
    function ng() {
      if (R === 0 || R === 3 || R === 2)
        R = 4;
      N === null || (le & 268435455) === 0 && (wh & 268435455) === 0 || Jh(N, Z);
    }
    function Ph(a, b) {
      var c = H;
      H |= 2;
      var d = Qh();
      if (N !== a || Z !== b)
        Ah = null, Rh(a, b);
      do
        try {
          Zh();
          break;
        } catch (e) {
          Th(a, e);
        }
      while (1);
      Ud();
      H = c;
      th.current = d;
      if (X !== null)
        throw Error(n(261));
      N = null;
      Z = 0;
      return R;
    }
    function Zh() {
      for (;X !== null; )
        $h(X);
    }
    function Sh() {
      for (;X !== null && !Lc(); )
        $h(X);
    }
    function $h(a) {
      var b = ai(a.alternate, a, $f);
      a.memoizedProps = a.pendingProps;
      b === null ? Yh(a) : X = b;
      uh.current = null;
    }
    function Yh(a) {
      var b = a;
      do {
        var c = b.alternate;
        a = b.return;
        if ((b.flags & 32768) === 0) {
          if (c = Bg(c, b, $f), c !== null) {
            X = c;
            return;
          }
        } else {
          c = Fg(c, b);
          if (c !== null) {
            c.flags &= 32767;
            X = c;
            return;
          }
          if (a !== null)
            a.flags |= 32768, a.subtreeFlags = 0, a.deletions = null;
          else {
            R = 6;
            X = null;
            return;
          }
        }
        b = b.sibling;
        if (b !== null) {
          X = b;
          return;
        }
        X = b = a;
      } while (b !== null);
      R === 0 && (R = 5);
    }
    function Wh(a, b, c) {
      var d = C, e = W.transition;
      try {
        W.transition = null, C = 1, bi(a, b, c, d);
      } finally {
        W.transition = e, C = d;
      }
      return null;
    }
    function bi(a, b, c, d) {
      do
        Oh();
      while (Dh !== null);
      if ((H & 6) !== 0)
        throw Error(n(327));
      c = a.finishedWork;
      var e = a.finishedLanes;
      if (c === null)
        return null;
      a.finishedWork = null;
      a.finishedLanes = 0;
      if (c === a.current)
        throw Error(n(177));
      a.callbackNode = null;
      a.callbackPriority = 0;
      var f = c.lanes | c.childLanes;
      Gc(a, f);
      a === N && (X = N = null, Z = 0);
      (c.subtreeFlags & 2064) === 0 && (c.flags & 2064) === 0 || Ch || (Ch = true, Mh(Pc, function() {
        Oh();
        return null;
      }));
      f = (c.flags & 15990) !== 0;
      if ((c.subtreeFlags & 15990) !== 0 || f) {
        f = W.transition;
        W.transition = null;
        var g = C;
        C = 1;
        var h = H;
        H |= 4;
        uh.current = null;
        Lg(a, c);
        $g(c, a);
        Ia(a.containerInfo);
        a.current = c;
        dh(c, a, e);
        Mc();
        H = h;
        C = g;
        W.transition = f;
      } else
        a.current = c;
      Ch && (Ch = false, Dh = a, Eh = e);
      f = a.pendingLanes;
      f === 0 && (Mf = null);
      Tc(c.stateNode, d);
      Kh(a, D());
      if (b !== null)
        for (d = a.onRecoverableError, c = 0;c < b.length; c++)
          e = b[c], d(e.value, { componentStack: e.stack, digest: e.digest });
      if (Jf)
        throw Jf = false, a = Kf, Kf = null, a;
      (Eh & 1) !== 0 && a.tag !== 0 && Oh();
      f = a.pendingLanes;
      (f & 1) !== 0 ? a === Gh ? Fh++ : (Fh = 0, Gh = a) : Fh = 0;
      ad();
      return null;
    }
    function Oh() {
      if (Dh !== null) {
        var a = Ic(Eh), b = W.transition, c = C;
        try {
          W.transition = null;
          C = 16 > a ? 16 : a;
          if (Dh === null)
            var d = false;
          else {
            a = Dh;
            Dh = null;
            Eh = 0;
            if ((H & 6) !== 0)
              throw Error(n(331));
            var e = H;
            H |= 4;
            for (T = a.current;T !== null; ) {
              var f = T, g = f.child;
              if ((T.flags & 16) !== 0) {
                var h = f.deletions;
                if (h !== null) {
                  for (var k = 0;k < h.length; k++) {
                    var l = h[k];
                    for (T = l;T !== null; ) {
                      var m = T;
                      switch (m.tag) {
                        case 0:
                        case 11:
                        case 15:
                          Mg(8, m, f);
                      }
                      var r = m.child;
                      if (r !== null)
                        r.return = m, T = r;
                      else
                        for (;T !== null; ) {
                          m = T;
                          var { sibling: p, return: B } = m;
                          Pg(m);
                          if (m === l) {
                            T = null;
                            break;
                          }
                          if (p !== null) {
                            p.return = B;
                            T = p;
                            break;
                          }
                          T = B;
                        }
                    }
                  }
                  var w = f.alternate;
                  if (w !== null) {
                    var Y = w.child;
                    if (Y !== null) {
                      w.child = null;
                      do {
                        var ya = Y.sibling;
                        Y.sibling = null;
                        Y = ya;
                      } while (Y !== null);
                    }
                  }
                  T = f;
                }
              }
              if ((f.subtreeFlags & 2064) !== 0 && g !== null)
                g.return = f, T = g;
              else
                b:
                  for (;T !== null; ) {
                    f = T;
                    if ((f.flags & 2048) !== 0)
                      switch (f.tag) {
                        case 0:
                        case 11:
                        case 15:
                          Mg(9, f, f.return);
                      }
                    var E = f.sibling;
                    if (E !== null) {
                      E.return = f.return;
                      T = E;
                      break b;
                    }
                    T = f.return;
                  }
            }
            var u = a.current;
            for (T = u;T !== null; ) {
              g = T;
              var t = g.child;
              if ((g.subtreeFlags & 2064) !== 0 && t !== null)
                t.return = g, T = t;
              else
                b:
                  for (g = u;T !== null; ) {
                    h = T;
                    if ((h.flags & 2048) !== 0)
                      try {
                        switch (h.tag) {
                          case 0:
                          case 11:
                          case 15:
                            Ng(9, h);
                        }
                      } catch (lc) {
                        U(h, h.return, lc);
                      }
                    if (h === g) {
                      T = null;
                      break b;
                    }
                    var Db = h.sibling;
                    if (Db !== null) {
                      Db.return = h.return;
                      T = Db;
                      break b;
                    }
                    T = h.return;
                  }
            }
            H = e;
            ad();
            if (Sc && typeof Sc.onPostCommitFiberRoot === "function")
              try {
                Sc.onPostCommitFiberRoot(Rc, a);
              } catch (lc) {}
            d = true;
          }
          return d;
        } finally {
          C = c, W.transition = b;
        }
      }
      return false;
    }
    function ci(a, b, c) {
      b = Ef(c, b);
      b = If(a, b, 1);
      a = he(a, b, 1);
      b = O();
      a !== null && (Fc(a, 1, b), Kh(a, b));
    }
    function U(a, b, c) {
      if (a.tag === 3)
        ci(a, a, c);
      else
        for (;b !== null; ) {
          if (b.tag === 3) {
            ci(b, a, c);
            break;
          } else if (b.tag === 1) {
            var d = b.stateNode;
            if (typeof b.type.getDerivedStateFromError === "function" || typeof d.componentDidCatch === "function" && (Mf === null || !Mf.has(d))) {
              a = Ef(c, a);
              a = Lf(b, a, 1);
              b = he(b, a, 1);
              a = O();
              b !== null && (Fc(b, 1, a), Kh(b, a));
              break;
            }
          }
          b = b.return;
        }
    }
    function Of(a, b, c) {
      var d = a.pingCache;
      d !== null && d.delete(b);
      b = O();
      a.pingedLanes |= a.suspendedLanes & c;
      N === a && (Z & c) === c && (R === 4 || R === 3 && (Z & 130023424) === Z && 500 > D() - bh ? Rh(a, 0) : xh |= c);
      Kh(a, b);
    }
    function di(a, b) {
      b === 0 && ((a.mode & 1) === 0 ? b = 1 : (b = xc, xc <<= 1, (xc & 130023424) === 0 && (xc = 4194304)));
      var c = O();
      a = ce(a, b);
      a !== null && (Fc(a, b, c), Kh(a, c));
    }
    function og(a) {
      var b = a.memoizedState, c = 0;
      b !== null && (c = b.retryLane);
      di(a, c);
    }
    function Yg(a, b) {
      var c = 0;
      switch (a.tag) {
        case 13:
          var d = a.stateNode;
          var e = a.memoizedState;
          e !== null && (c = e.retryLane);
          break;
        case 19:
          d = a.stateNode;
          break;
        default:
          throw Error(n(314));
      }
      d !== null && d.delete(b);
      di(a, c);
    }
    var ai;
    ai = function(a, b, c) {
      if (a !== null)
        if (a.memoizedProps !== b.pendingProps || z.current)
          G = true;
        else {
          if ((a.lanes & c) === 0 && (b.flags & 128) === 0)
            return G = false, sg(a, b, c);
          G = (a.flags & 131072) !== 0 ? true : false;
        }
      else
        G = false, F && (b.flags & 1048576) !== 0 && ld(b, ed, b.index);
      b.lanes = 0;
      switch (b.tag) {
        case 2:
          var d = b.type;
          cg(a, b);
          a = b.pendingProps;
          var e = mc(b, x.current);
          Yd(b, c);
          e = He(null, b, d, a, e, c);
          var f = Me();
          b.flags |= 1;
          typeof e === "object" && e !== null && typeof e.render === "function" && e.$$typeof === undefined ? (b.tag = 1, b.memoizedState = null, b.updateQueue = null, A(d) ? (f = true, qc(b)) : f = false, b.memoizedState = e.state !== null && e.state !== undefined ? e.state : null, ee(b), e.updater = zf, b.stateNode = e, e._reactInternals = b, Df(b, d, a, c), b = dg(null, b, d, true, f, c)) : (b.tag = 0, F && f && md(b), P(null, b, e, c), b = b.child);
          return b;
        case 16:
          d = b.elementType;
          a: {
            cg(a, b);
            a = b.pendingProps;
            e = d._init;
            d = e(d._payload);
            b.type = d;
            e = b.tag = ei(d);
            a = xf(d, a);
            switch (e) {
              case 0:
                b = Xf(null, b, d, a, c);
                break a;
              case 1:
                b = bg(null, b, d, a, c);
                break a;
              case 11:
                b = Sf(null, b, d, a, c);
                break a;
              case 14:
                b = Uf(null, b, d, xf(d.type, a), c);
                break a;
            }
            throw Error(n(306, d, ""));
          }
          return b;
        case 0:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : xf(d, e), Xf(a, b, d, e, c);
        case 1:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : xf(d, e), bg(a, b, d, e, c);
        case 3:
          a: {
            eg(b);
            if (a === null)
              throw Error(n(387));
            d = b.pendingProps;
            f = b.memoizedState;
            e = f.element;
            fe(a, b);
            ke(b, d, null, c);
            var g = b.memoizedState;
            d = g.element;
            if (Va && f.isDehydrated)
              if (f = { element: d, isDehydrated: false, cache: g.cache, pendingSuspenseBoundaries: g.pendingSuspenseBoundaries, transitions: g.transitions }, b.updateQueue.baseState = f, b.memoizedState = f, b.flags & 256) {
                e = Ef(Error(n(423)), b);
                b = fg(a, b, d, c, e);
                break a;
              } else if (d !== e) {
                e = Ef(Error(n(424)), b);
                b = fg(a, b, d, c, e);
                break a;
              } else
                for (Va && (pd = Pb(b.stateNode.containerInfo), od = b, F = true, rd = null, qd = false), c = Pd(b, null, d, c), b.child = c;c; )
                  c.flags = c.flags & -3 | 4096, c = c.sibling;
            else {
              Ad();
              if (d === e) {
                b = Tf(a, b, c);
                break a;
              }
              P(a, b, d, c);
            }
            b = b.child;
          }
          return b;
        case 5:
          return ue(b), a === null && wd(b), d = b.type, e = b.pendingProps, f = a !== null ? a.memoizedProps : null, g = e.children, Na(d, e) ? g = null : f !== null && Na(d, f) && (b.flags |= 32), ag(a, b), P(a, b, g, c), b.child;
        case 6:
          return a === null && wd(b), null;
        case 13:
          return ig(a, b, c);
        case 4:
          return se(b, b.stateNode.containerInfo), d = b.pendingProps, a === null ? b.child = Od(b, null, d, c) : P(a, b, d, c), b.child;
        case 11:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : xf(d, e), Sf(a, b, d, e, c);
        case 7:
          return P(a, b, b.pendingProps, c), b.child;
        case 8:
          return P(a, b, b.pendingProps.children, c), b.child;
        case 12:
          return P(a, b, b.pendingProps.children, c), b.child;
        case 10:
          a: {
            d = b.type._context;
            e = b.pendingProps;
            f = b.memoizedProps;
            g = e.value;
            Vd(b, d, g);
            if (f !== null)
              if (Vc(f.value, g)) {
                if (f.children === e.children && !z.current) {
                  b = Tf(a, b, c);
                  break a;
                }
              } else
                for (f = b.child, f !== null && (f.return = b);f !== null; ) {
                  var h = f.dependencies;
                  if (h !== null) {
                    g = f.child;
                    for (var k = h.firstContext;k !== null; ) {
                      if (k.context === d) {
                        if (f.tag === 1) {
                          k = ge(-1, c & -c);
                          k.tag = 2;
                          var l = f.updateQueue;
                          if (l !== null) {
                            l = l.shared;
                            var m = l.pending;
                            m === null ? k.next = k : (k.next = m.next, m.next = k);
                            l.pending = k;
                          }
                        }
                        f.lanes |= c;
                        k = f.alternate;
                        k !== null && (k.lanes |= c);
                        Xd(f.return, c, b);
                        h.lanes |= c;
                        break;
                      }
                      k = k.next;
                    }
                  } else if (f.tag === 10)
                    g = f.type === b.type ? null : f.child;
                  else if (f.tag === 18) {
                    g = f.return;
                    if (g === null)
                      throw Error(n(341));
                    g.lanes |= c;
                    h = g.alternate;
                    h !== null && (h.lanes |= c);
                    Xd(g, c, b);
                    g = f.sibling;
                  } else
                    g = f.child;
                  if (g !== null)
                    g.return = f;
                  else
                    for (g = f;g !== null; ) {
                      if (g === b) {
                        g = null;
                        break;
                      }
                      f = g.sibling;
                      if (f !== null) {
                        f.return = g.return;
                        g = f;
                        break;
                      }
                      g = g.return;
                    }
                  f = g;
                }
            P(a, b, e.children, c);
            b = b.child;
          }
          return b;
        case 9:
          return e = b.type, d = b.pendingProps.children, Yd(b, c), e = Zd(e), d = d(e), b.flags |= 1, P(a, b, d, c), b.child;
        case 14:
          return d = b.type, e = xf(d, b.pendingProps), e = xf(d.type, e), Uf(a, b, d, e, c);
        case 15:
          return Wf(a, b, b.type, b.pendingProps, c);
        case 17:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : xf(d, e), cg(a, b), b.tag = 1, A(d) ? (a = true, qc(b)) : a = false, Yd(b, c), Bf(b, d, e), Df(b, d, e, c), dg(null, b, d, true, a, c);
        case 19:
          return rg(a, b, c);
        case 22:
          return Yf(a, b, c);
      }
      throw Error(n(156, b.tag));
    };
    function Mh(a, b) {
      return Jc(a, b);
    }
    function fi(a, b, c, d) {
      this.tag = a;
      this.key = c;
      this.sibling = this.child = this.return = this.stateNode = this.type = this.elementType = null;
      this.index = 0;
      this.ref = null;
      this.pendingProps = b;
      this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null;
      this.mode = d;
      this.subtreeFlags = this.flags = 0;
      this.deletions = null;
      this.childLanes = this.lanes = 0;
      this.alternate = null;
    }
    function td(a, b, c, d) {
      return new fi(a, b, c, d);
    }
    function Vf(a) {
      a = a.prototype;
      return !(!a || !a.isReactComponent);
    }
    function ei(a) {
      if (typeof a === "function")
        return Vf(a) ? 1 : 0;
      if (a !== undefined && a !== null) {
        a = a.$$typeof;
        if (a === ma)
          return 11;
        if (a === pa)
          return 14;
      }
      return 2;
    }
    function Jd(a, b) {
      var c = a.alternate;
      c === null ? (c = td(a.tag, b, a.key, a.mode), c.elementType = a.elementType, c.type = a.type, c.stateNode = a.stateNode, c.alternate = a, a.alternate = c) : (c.pendingProps = b, c.type = a.type, c.flags = 0, c.subtreeFlags = 0, c.deletions = null);
      c.flags = a.flags & 14680064;
      c.childLanes = a.childLanes;
      c.lanes = a.lanes;
      c.child = a.child;
      c.memoizedProps = a.memoizedProps;
      c.memoizedState = a.memoizedState;
      c.updateQueue = a.updateQueue;
      b = a.dependencies;
      c.dependencies = b === null ? null : { lanes: b.lanes, firstContext: b.firstContext };
      c.sibling = a.sibling;
      c.index = a.index;
      c.ref = a.ref;
      return c;
    }
    function Ld(a, b, c, d, e, f) {
      var g = 2;
      d = a;
      if (typeof a === "function")
        Vf(a) && (g = 1);
      else if (typeof a === "string")
        g = 5;
      else
        a:
          switch (a) {
            case ha:
              return Nd(c.children, e, f, b);
            case ia:
              g = 8;
              e |= 8;
              break;
            case ja:
              return a = td(12, c, b, e | 2), a.elementType = ja, a.lanes = f, a;
            case na:
              return a = td(13, c, b, e), a.elementType = na, a.lanes = f, a;
            case oa:
              return a = td(19, c, b, e), a.elementType = oa, a.lanes = f, a;
            case ra:
              return jg(c, e, f, b);
            default:
              if (typeof a === "object" && a !== null)
                switch (a.$$typeof) {
                  case ka:
                    g = 10;
                    break a;
                  case la:
                    g = 9;
                    break a;
                  case ma:
                    g = 11;
                    break a;
                  case pa:
                    g = 14;
                    break a;
                  case qa:
                    g = 16;
                    d = null;
                    break a;
                }
              throw Error(n(130, a == null ? a : typeof a, ""));
          }
      b = td(g, c, b, e);
      b.elementType = a;
      b.type = d;
      b.lanes = f;
      return b;
    }
    function Nd(a, b, c, d) {
      a = td(7, a, d, b);
      a.lanes = c;
      return a;
    }
    function jg(a, b, c, d) {
      a = td(22, a, d, b);
      a.elementType = ra;
      a.lanes = c;
      a.stateNode = { isHidden: false };
      return a;
    }
    function Kd(a, b, c) {
      a = td(6, a, null, b);
      a.lanes = c;
      return a;
    }
    function Md(a, b, c) {
      b = td(4, a.children !== null ? a.children : [], a.key, b);
      b.lanes = c;
      b.stateNode = { containerInfo: a.containerInfo, pendingChildren: null, implementation: a.implementation };
      return b;
    }
    function gi(a, b, c, d, e) {
      this.tag = b;
      this.containerInfo = a;
      this.finishedWork = this.pingCache = this.current = this.pendingChildren = null;
      this.timeoutHandle = Ra;
      this.callbackNode = this.pendingContext = this.context = null;
      this.callbackPriority = 0;
      this.eventTimes = Ec(0);
      this.expirationTimes = Ec(-1);
      this.entangledLanes = this.finishedLanes = this.mutableReadLanes = this.expiredLanes = this.pingedLanes = this.suspendedLanes = this.pendingLanes = 0;
      this.entanglements = Ec(0);
      this.identifierPrefix = d;
      this.onRecoverableError = e;
      Va && (this.mutableSourceEagerHydrationData = null);
    }
    function hi(a, b, c, d, e, f, g, h, k) {
      a = new gi(a, b, c, h, k);
      b === 1 ? (b = 1, f === true && (b |= 8)) : b = 0;
      f = td(3, null, null, b);
      a.current = f;
      f.stateNode = a;
      f.memoizedState = { element: d, isDehydrated: c, cache: null, transitions: null, pendingSuspenseBoundaries: null };
      ee(f);
      return a;
    }
    function ii(a) {
      if (!a)
        return jc;
      a = a._reactInternals;
      a: {
        if (wa(a) !== a || a.tag !== 1)
          throw Error(n(170));
        var b = a;
        do {
          switch (b.tag) {
            case 3:
              b = b.stateNode.context;
              break a;
            case 1:
              if (A(b.type)) {
                b = b.stateNode.__reactInternalMemoizedMergedChildContext;
                break a;
              }
          }
          b = b.return;
        } while (b !== null);
        throw Error(n(171));
      }
      if (a.tag === 1) {
        var c = a.type;
        if (A(c))
          return pc(a, c, b);
      }
      return b;
    }
    function ji(a) {
      var b = a._reactInternals;
      if (b === undefined) {
        if (typeof a.render === "function")
          throw Error(n(188));
        a = Object.keys(a).join(",");
        throw Error(n(268, a));
      }
      a = Aa(b);
      return a === null ? null : a.stateNode;
    }
    function ki(a, b) {
      a = a.memoizedState;
      if (a !== null && a.dehydrated !== null) {
        var c = a.retryLane;
        a.retryLane = c !== 0 && c < b ? c : b;
      }
    }
    function li(a, b) {
      ki(a, b);
      (a = a.alternate) && ki(a, b);
    }
    function mi(a) {
      a = Aa(a);
      return a === null ? null : a.stateNode;
    }
    function ni() {
      return null;
    }
    exports2.attemptContinuousHydration = function(a) {
      if (a.tag === 13) {
        var b = ce(a, 134217728);
        if (b !== null) {
          var c = O();
          af(b, a, 134217728, c);
        }
        li(a, 134217728);
      }
    };
    exports2.attemptDiscreteHydration = function(a) {
      if (a.tag === 13) {
        var b = ce(a, 1);
        if (b !== null) {
          var c = O();
          af(b, a, 1, c);
        }
        li(a, 1);
      }
    };
    exports2.attemptHydrationAtCurrentPriority = function(a) {
      if (a.tag === 13) {
        var b = tf(a), c = ce(a, b);
        if (c !== null) {
          var d = O();
          af(c, a, b, d);
        }
        li(a, b);
      }
    };
    exports2.attemptSynchronousHydration = function(a) {
      switch (a.tag) {
        case 3:
          var b = a.stateNode;
          if (b.current.memoizedState.isDehydrated) {
            var c = yc(b.pendingLanes);
            c !== 0 && (Hc(b, c | 1), Kh(b, D()), (H & 6) === 0 && (Bh(), ad()));
          }
          break;
        case 13:
          Xh(function() {
            var b2 = ce(a, 1);
            if (b2 !== null) {
              var c2 = O();
              af(b2, a, 1, c2);
            }
          }), li(a, 1);
      }
    };
    exports2.batchedUpdates = function(a, b) {
      var c = H;
      H |= 1;
      try {
        return a(b);
      } finally {
        H = c, H === 0 && (Bh(), Xc && ad());
      }
    };
    exports2.createComponentSelector = function(a) {
      return { $$typeof: hh, value: a };
    };
    exports2.createContainer = function(a, b, c, d, e, f, g) {
      return hi(a, b, false, null, c, d, e, f, g);
    };
    exports2.createHasPseudoClassSelector = function(a) {
      return { $$typeof: ih, value: a };
    };
    exports2.createHydrationContainer = function(a, b, c, d, e, f, g, h, k) {
      a = hi(c, d, true, a, e, f, g, h, k);
      a.context = ii(null);
      c = a.current;
      d = O();
      e = tf(c);
      f = ge(d, e);
      f.callback = b !== undefined && b !== null ? b : null;
      he(c, f, e);
      a.current.lanes = e;
      Fc(a, e, d);
      Kh(a, d);
      return a;
    };
    exports2.createPortal = function(a, b, c) {
      var d = 3 < arguments.length && arguments[3] !== undefined ? arguments[3] : null;
      return { $$typeof: fa, key: d == null ? null : "" + d, children: a, containerInfo: b, implementation: c };
    };
    exports2.createRoleSelector = function(a) {
      return { $$typeof: jh, value: a };
    };
    exports2.createTestNameSelector = function(a) {
      return { $$typeof: kh, value: a };
    };
    exports2.createTextSelector = function(a) {
      return { $$typeof: lh, value: a };
    };
    exports2.deferredUpdates = function(a) {
      var b = C, c = W.transition;
      try {
        return W.transition = null, C = 16, a();
      } finally {
        C = b, W.transition = c;
      }
    };
    exports2.discreteUpdates = function(a, b, c, d, e) {
      var f = C, g = W.transition;
      try {
        return W.transition = null, C = 1, a(b, c, d, e);
      } finally {
        C = f, W.transition = g, H === 0 && Bh();
      }
    };
    exports2.findAllNodes = rh;
    exports2.findBoundingRects = function(a, b) {
      if (!bb)
        throw Error(n(363));
      b = rh(a, b);
      a = [];
      for (var c = 0;c < b.length; c++)
        a.push(db(b[c]));
      for (b = a.length - 1;0 < b; b--) {
        c = a[b];
        for (var d = c.x, e = d + c.width, f = c.y, g = f + c.height, h = b - 1;0 <= h; h--)
          if (b !== h) {
            var k = a[h], l = k.x, m = l + k.width, r = k.y, p = r + k.height;
            if (d >= l && f >= r && e <= m && g <= p) {
              a.splice(b, 1);
              break;
            } else if (!(d !== l || c.width !== k.width || p < f || r > g)) {
              r > f && (k.height += r - f, k.y = f);
              p < g && (k.height = g - r);
              a.splice(b, 1);
              break;
            } else if (!(f !== r || c.height !== k.height || m < d || l > e)) {
              l > d && (k.width += l - d, k.x = d);
              m < e && (k.width = e - l);
              a.splice(b, 1);
              break;
            }
          }
      }
      return a;
    };
    exports2.findHostInstance = ji;
    exports2.findHostInstanceWithNoPortals = function(a) {
      a = za(a);
      a = a !== null ? Ca(a) : null;
      return a === null ? null : a.stateNode;
    };
    exports2.findHostInstanceWithWarning = function(a) {
      return ji(a);
    };
    exports2.flushControlled = function(a) {
      var b = H;
      H |= 1;
      var c = W.transition, d = C;
      try {
        W.transition = null, C = 1, a();
      } finally {
        C = d, W.transition = c, H = b, H === 0 && (Bh(), ad());
      }
    };
    exports2.flushPassiveEffects = Oh;
    exports2.flushSync = Xh;
    exports2.focusWithin = function(a, b) {
      if (!bb)
        throw Error(n(363));
      a = nh(a);
      b = qh(a, b);
      b = Array.from(b);
      for (a = 0;a < b.length; ) {
        var c = b[a++];
        if (!fb(c)) {
          if (c.tag === 5 && hb(c.stateNode))
            return true;
          for (c = c.child;c !== null; )
            b.push(c), c = c.sibling;
        }
      }
      return false;
    };
    exports2.getCurrentUpdatePriority = function() {
      return C;
    };
    exports2.getFindAllNodesFailureDescription = function(a, b) {
      if (!bb)
        throw Error(n(363));
      var c = 0, d = [];
      a = [nh(a), 0];
      for (var e = 0;e < a.length; ) {
        var f = a[e++], g = a[e++], h = b[g];
        if (f.tag !== 5 || !fb(f)) {
          if (oh(f, h) && (d.push(ph(h)), g++, g > c && (c = g)), g < b.length)
            for (f = f.child;f !== null; )
              a.push(f, g), f = f.sibling;
        }
      }
      if (c < b.length) {
        for (a = [];c < b.length; c++)
          a.push(ph(b[c]));
        return `findAllNodes was able to match part of the selector:
  ` + (d.join(" > ") + `

No matching component was found for:
  `) + a.join(" > ");
      }
      return null;
    };
    exports2.getPublicRootInstance = function(a) {
      a = a.current;
      if (!a.child)
        return null;
      switch (a.child.tag) {
        case 5:
          return Ea(a.child.stateNode);
        default:
          return a.child.stateNode;
      }
    };
    exports2.injectIntoDevTools = function(a) {
      a = { bundleType: a.bundleType, version: a.version, rendererPackageName: a.rendererPackageName, rendererConfig: a.rendererConfig, overrideHookState: null, overrideHookStateDeletePath: null, overrideHookStateRenamePath: null, overrideProps: null, overridePropsDeletePath: null, overridePropsRenamePath: null, setErrorHandler: null, setSuspenseHandler: null, scheduleUpdate: null, currentDispatcherRef: da.ReactCurrentDispatcher, findHostInstanceByFiber: mi, findFiberByHostInstance: a.findFiberByHostInstance || ni, findHostInstancesForRefresh: null, scheduleRefresh: null, scheduleRoot: null, setRefreshHandler: null, getCurrentFiber: null, reconcilerVersion: "18.3.1" };
      if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ === "undefined")
        a = false;
      else {
        var b = __REACT_DEVTOOLS_GLOBAL_HOOK__;
        if (b.isDisabled || !b.supportsFiber)
          a = true;
        else {
          try {
            Rc = b.inject(a), Sc = b;
          } catch (c) {}
          a = b.checkDCE ? true : false;
        }
      }
      return a;
    };
    exports2.isAlreadyRendering = function() {
      return false;
    };
    exports2.observeVisibleRects = function(a, b, c, d) {
      if (!bb)
        throw Error(n(363));
      a = rh(a, b);
      var e = ib(a, c, d).disconnect;
      return { disconnect: function() {
        e();
      } };
    };
    exports2.registerMutableSourceForHydration = function(a, b) {
      var c = b._getVersion;
      c = c(b._source);
      a.mutableSourceEagerHydrationData == null ? a.mutableSourceEagerHydrationData = [b, c] : a.mutableSourceEagerHydrationData.push(b, c);
    };
    exports2.runWithPriority = function(a, b) {
      var c = C;
      try {
        return C = a, b();
      } finally {
        C = c;
      }
    };
    exports2.shouldError = function() {
      return null;
    };
    exports2.shouldSuspend = function() {
      return false;
    };
    exports2.updateContainer = function(a, b, c, d) {
      var e = b.current, f = O(), g = tf(e);
      c = ii(c);
      b.context === null ? b.context = c : b.pendingContext = c;
      b = ge(f, g);
      b.payload = { element: a };
      d = d === undefined ? null : d;
      d !== null && (b.callback = d);
      a = he(e, b, g);
      a !== null && (af(a, e, g, f), ie(a, e, g));
      return g;
    };
    return exports2;
  };
});

// node_modules/react-reconciler/index.js
var require_react_reconciler = __commonJS((exports, module) => {
  if (true) {
    module.exports = require_react_reconciler_production_min();
  } else {}
});

// node_modules/react-reconciler/cjs/react-reconciler-constants.production.min.js
var require_react_reconciler_constants_production_min = __commonJS((exports) => {
  exports.ConcurrentRoot = 1;
  exports.ContinuousEventPriority = 4;
  exports.DefaultEventPriority = 16;
  exports.DiscreteEventPriority = 1;
  exports.IdleEventPriority = 536870912;
  exports.LegacyRoot = 0;
});

// node_modules/react-reconciler/constants.js
var require_constants = __commonJS((exports, module) => {
  if (true) {
    module.exports = require_react_reconciler_constants_production_min();
  } else {}
});

// node_modules/emoji-regex/index.js
var require_emoji_regex = __commonJS((exports, module) => {
  module.exports = () => {
    return /[#*0-9]\uFE0F?\u20E3|[\xA9\xAE\u203C\u2049\u2122\u2139\u2194-\u2199\u21A9\u21AA\u231A\u231B\u2328\u23CF\u23ED-\u23EF\u23F1\u23F2\u23F8-\u23FA\u24C2\u25AA\u25AB\u25B6\u25C0\u25FB\u25FC\u25FE\u2600-\u2604\u260E\u2611\u2614\u2615\u2618\u2620\u2622\u2623\u2626\u262A\u262E\u262F\u2638-\u263A\u2640\u2642\u2648-\u2653\u265F\u2660\u2663\u2665\u2666\u2668\u267B\u267E\u267F\u2692\u2694-\u2697\u2699\u269B\u269C\u26A0\u26A7\u26AA\u26B0\u26B1\u26BD\u26BE\u26C4\u26C8\u26CF\u26D1\u26E9\u26F0-\u26F5\u26F7\u26F8\u26FA\u2702\u2708\u2709\u270F\u2712\u2714\u2716\u271D\u2721\u2733\u2734\u2744\u2747\u2757\u2763\u27A1\u2934\u2935\u2B05-\u2B07\u2B1B\u2B1C\u2B55\u3030\u303D\u3297\u3299]\uFE0F?|[\u261D\u270C\u270D](?:\uD83C[\uDFFB-\uDFFF]|\uFE0F)?|[\u270A\u270B](?:\uD83C[\uDFFB-\uDFFF])?|[\u23E9-\u23EC\u23F0\u23F3\u25FD\u2693\u26A1\u26AB\u26C5\u26CE\u26D4\u26EA\u26FD\u2705\u2728\u274C\u274E\u2753-\u2755\u2795-\u2797\u27B0\u27BF\u2B50]|\u26D3\uFE0F?(?:\u200D\uD83D\uDCA5)?|\u26F9(?:\uD83C[\uDFFB-\uDFFF]|\uFE0F)?(?:\u200D[\u2640\u2642]\uFE0F?)?|\u2764\uFE0F?(?:\u200D(?:\uD83D\uDD25|\uD83E\uDE79))?|\uD83C(?:[\uDC04\uDD70\uDD71\uDD7E\uDD7F\uDE02\uDE37\uDF21\uDF24-\uDF2C\uDF36\uDF7D\uDF96\uDF97\uDF99-\uDF9B\uDF9E\uDF9F\uDFCD\uDFCE\uDFD4-\uDFDF\uDFF5\uDFF7]\uFE0F?|[\uDF85\uDFC2\uDFC7](?:\uD83C[\uDFFB-\uDFFF])?|[\uDFC4\uDFCA](?:\uD83C[\uDFFB-\uDFFF])?(?:\u200D[\u2640\u2642]\uFE0F?)?|[\uDFCB\uDFCC](?:\uD83C[\uDFFB-\uDFFF]|\uFE0F)?(?:\u200D[\u2640\u2642]\uFE0F?)?|[\uDCCF\uDD8E\uDD91-\uDD9A\uDE01\uDE1A\uDE2F\uDE32-\uDE36\uDE38-\uDE3A\uDE50\uDE51\uDF00-\uDF20\uDF2D-\uDF35\uDF37-\uDF43\uDF45-\uDF4A\uDF4C-\uDF7C\uDF7E-\uDF84\uDF86-\uDF93\uDFA0-\uDFC1\uDFC5\uDFC6\uDFC8\uDFC9\uDFCF-\uDFD3\uDFE0-\uDFF0\uDFF8-\uDFFF]|\uDDE6\uD83C[\uDDE8-\uDDEC\uDDEE\uDDF1\uDDF2\uDDF4\uDDF6-\uDDFA\uDDFC\uDDFD\uDDFF]|\uDDE7\uD83C[\uDDE6\uDDE7\uDDE9-\uDDEF\uDDF1-\uDDF4\uDDF6-\uDDF9\uDDFB\uDDFC\uDDFE\uDDFF]|\uDDE8\uD83C[\uDDE6\uDDE8\uDDE9\uDDEB-\uDDEE\uDDF0-\uDDF7\uDDFA-\uDDFF]|\uDDE9\uD83C[\uDDEA\uDDEC\uDDEF\uDDF0\uDDF2\uDDF4\uDDFF]|\uDDEA\uD83C[\uDDE6\uDDE8\uDDEA\uDDEC\uDDED\uDDF7-\uDDFA]|\uDDEB\uD83C[\uDDEE-\uDDF0\uDDF2\uDDF4\uDDF7]|\uDDEC\uD83C[\uDDE6\uDDE7\uDDE9-\uDDEE\uDDF1-\uDDF3\uDDF5-\uDDFA\uDDFC\uDDFE]|\uDDED\uD83C[\uDDF0\uDDF2\uDDF3\uDDF7\uDDF9\uDDFA]|\uDDEE\uD83C[\uDDE8-\uDDEA\uDDF1-\uDDF4\uDDF6-\uDDF9]|\uDDEF\uD83C[\uDDEA\uDDF2\uDDF4\uDDF5]|\uDDF0\uD83C[\uDDEA\uDDEC-\uDDEE\uDDF2\uDDF3\uDDF5\uDDF7\uDDFC\uDDFE\uDDFF]|\uDDF1\uD83C[\uDDE6-\uDDE8\uDDEE\uDDF0\uDDF7-\uDDFB\uDDFE]|\uDDF2\uD83C[\uDDE6\uDDE8-\uDDED\uDDF0-\uDDFF]|\uDDF3\uD83C[\uDDE6\uDDE8\uDDEA-\uDDEC\uDDEE\uDDF1\uDDF4\uDDF5\uDDF7\uDDFA\uDDFF]|\uDDF4\uD83C\uDDF2|\uDDF5\uD83C[\uDDE6\uDDEA-\uDDED\uDDF0-\uDDF3\uDDF7-\uDDF9\uDDFC\uDDFE]|\uDDF6\uD83C\uDDE6|\uDDF7\uD83C[\uDDEA\uDDF4\uDDF8\uDDFA\uDDFC]|\uDDF8\uD83C[\uDDE6-\uDDEA\uDDEC-\uDDF4\uDDF7-\uDDF9\uDDFB\uDDFD-\uDDFF]|\uDDF9\uD83C[\uDDE6\uDDE8\uDDE9\uDDEB-\uDDED\uDDEF-\uDDF4\uDDF7\uDDF9\uDDFB\uDDFC\uDDFF]|\uDDFA\uD83C[\uDDE6\uDDEC\uDDF2\uDDF3\uDDF8\uDDFE\uDDFF]|\uDDFB\uD83C[\uDDE6\uDDE8\uDDEA\uDDEC\uDDEE\uDDF3\uDDFA]|\uDDFC\uD83C[\uDDEB\uDDF8]|\uDDFD\uD83C\uDDF0|\uDDFE\uD83C[\uDDEA\uDDF9]|\uDDFF\uD83C[\uDDE6\uDDF2\uDDFC]|\uDF44(?:\u200D\uD83D\uDFEB)?|\uDF4B(?:\u200D\uD83D\uDFE9)?|\uDFC3(?:\uD83C[\uDFFB-\uDFFF])?(?:\u200D(?:[\u2640\u2642]\uFE0F?(?:\u200D\u27A1\uFE0F?)?|\u27A1\uFE0F?))?|\uDFF3\uFE0F?(?:\u200D(?:\u26A7\uFE0F?|\uD83C\uDF08))?|\uDFF4(?:\u200D\u2620\uFE0F?|\uDB40\uDC67\uDB40\uDC62\uDB40(?:\uDC65\uDB40\uDC6E\uDB40\uDC67|\uDC73\uDB40\uDC63\uDB40\uDC74|\uDC77\uDB40\uDC6C\uDB40\uDC73)\uDB40\uDC7F)?)|\uD83D(?:[\uDC3F\uDCFD\uDD49\uDD4A\uDD6F\uDD70\uDD73\uDD76-\uDD79\uDD87\uDD8A-\uDD8D\uDDA5\uDDA8\uDDB1\uDDB2\uDDBC\uDDC2-\uDDC4\uDDD1-\uDDD3\uDDDC-\uDDDE\uDDE1\uDDE3\uDDE8\uDDEF\uDDF3\uDDFA\uDECB\uDECD-\uDECF\uDEE0-\uDEE5\uDEE9\uDEF0\uDEF3]\uFE0F?|[\uDC42\uDC43\uDC46-\uDC50\uDC66\uDC67\uDC6B-\uDC6D\uDC72\uDC74-\uDC76\uDC78\uDC7C\uDC83\uDC85\uDC8F\uDC91\uDCAA\uDD7A\uDD95\uDD96\uDE4C\uDE4F\uDEC0\uDECC](?:\uD83C[\uDFFB-\uDFFF])?|[\uDC6E-\uDC71\uDC73\uDC77\uDC81\uDC82\uDC86\uDC87\uDE45-\uDE47\uDE4B\uDE4D\uDE4E\uDEA3\uDEB4\uDEB5](?:\uD83C[\uDFFB-\uDFFF])?(?:\u200D[\u2640\u2642]\uFE0F?)?|[\uDD74\uDD90](?:\uD83C[\uDFFB-\uDFFF]|\uFE0F)?|[\uDC00-\uDC07\uDC09-\uDC14\uDC16-\uDC25\uDC27-\uDC3A\uDC3C-\uDC3E\uDC40\uDC44\uDC45\uDC51-\uDC65\uDC6A\uDC79-\uDC7B\uDC7D-\uDC80\uDC84\uDC88-\uDC8E\uDC90\uDC92-\uDCA9\uDCAB-\uDCFC\uDCFF-\uDD3D\uDD4B-\uDD4E\uDD50-\uDD67\uDDA4\uDDFB-\uDE2D\uDE2F-\uDE34\uDE37-\uDE41\uDE43\uDE44\uDE48-\uDE4A\uDE80-\uDEA2\uDEA4-\uDEB3\uDEB7-\uDEBF\uDEC1-\uDEC5\uDED0-\uDED2\uDED5-\uDED8\uDEDC-\uDEDF\uDEEB\uDEEC\uDEF4-\uDEFC\uDFE0-\uDFEB\uDFF0]|\uDC08(?:\u200D\u2B1B)?|\uDC15(?:\u200D\uD83E\uDDBA)?|\uDC26(?:\u200D(?:\u2B1B|\uD83D\uDD25))?|\uDC3B(?:\u200D\u2744\uFE0F?)?|\uDC41\uFE0F?(?:\u200D\uD83D\uDDE8\uFE0F?)?|\uDC68(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?\uDC68|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDC68\uDC69]\u200D\uD83D(?:\uDC66(?:\u200D\uD83D\uDC66)?|\uDC67(?:\u200D\uD83D[\uDC66\uDC67])?)|[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC66(?:\u200D\uD83D\uDC66)?|\uDC67(?:\u200D\uD83D[\uDC66\uDC67])?)|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]))|\uD83C(?:\uDFFB(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?\uDC68\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC68\uD83C[\uDFFC-\uDFFF])|\uD83E(?:[\uDD1D\uDEEF]\u200D\uD83D\uDC68\uD83C[\uDFFC-\uDFFF]|[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3])))?|\uDFFC(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?\uDC68\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC68\uD83C[\uDFFB\uDFFD-\uDFFF])|\uD83E(?:[\uDD1D\uDEEF]\u200D\uD83D\uDC68\uD83C[\uDFFB\uDFFD-\uDFFF]|[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3])))?|\uDFFD(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?\uDC68\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC68\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF])|\uD83E(?:[\uDD1D\uDEEF]\u200D\uD83D\uDC68\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF]|[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3])))?|\uDFFE(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?\uDC68\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC68\uD83C[\uDFFB-\uDFFD\uDFFF])|\uD83E(?:[\uDD1D\uDEEF]\u200D\uD83D\uDC68\uD83C[\uDFFB-\uDFFD\uDFFF]|[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3])))?|\uDFFF(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?\uDC68\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC68\uD83C[\uDFFB-\uDFFE])|\uD83E(?:[\uDD1D\uDEEF]\u200D\uD83D\uDC68\uD83C[\uDFFB-\uDFFE]|[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3])))?))?|\uDC69(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:\uDC8B\u200D\uD83D)?[\uDC68\uDC69]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC66(?:\u200D\uD83D\uDC66)?|\uDC67(?:\u200D\uD83D[\uDC66\uDC67])?|\uDC69\u200D\uD83D(?:\uDC66(?:\u200D\uD83D\uDC66)?|\uDC67(?:\u200D\uD83D[\uDC66\uDC67])?))|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]))|\uD83C(?:\uDFFB(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:[\uDC68\uDC69]|\uDC8B\u200D\uD83D[\uDC68\uDC69])\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC69\uD83C[\uDFFC-\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]|\uDD1D\u200D\uD83D[\uDC68\uDC69]\uD83C[\uDFFC-\uDFFF]|\uDEEF\u200D\uD83D\uDC69\uD83C[\uDFFC-\uDFFF])))?|\uDFFC(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:[\uDC68\uDC69]|\uDC8B\u200D\uD83D[\uDC68\uDC69])\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC69\uD83C[\uDFFB\uDFFD-\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]|\uDD1D\u200D\uD83D[\uDC68\uDC69]\uD83C[\uDFFB\uDFFD-\uDFFF]|\uDEEF\u200D\uD83D\uDC69\uD83C[\uDFFB\uDFFD-\uDFFF])))?|\uDFFD(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:[\uDC68\uDC69]|\uDC8B\u200D\uD83D[\uDC68\uDC69])\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC69\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]|\uDD1D\u200D\uD83D[\uDC68\uDC69]\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF]|\uDEEF\u200D\uD83D\uDC69\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF])))?|\uDFFE(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:[\uDC68\uDC69]|\uDC8B\u200D\uD83D[\uDC68\uDC69])\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC69\uD83C[\uDFFB-\uDFFD\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]|\uDD1D\u200D\uD83D[\uDC68\uDC69]\uD83C[\uDFFB-\uDFFD\uDFFF]|\uDEEF\u200D\uD83D\uDC69\uD83C[\uDFFB-\uDFFD\uDFFF])))?|\uDFFF(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D\uD83D(?:[\uDC68\uDC69]|\uDC8B\u200D\uD83D[\uDC68\uDC69])\uD83C[\uDFFB-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83D\uDC69\uD83C[\uDFFB-\uDFFE])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3]|\uDD1D\u200D\uD83D[\uDC68\uDC69]\uD83C[\uDFFB-\uDFFE]|\uDEEF\u200D\uD83D\uDC69\uD83C[\uDFFB-\uDFFE])))?))?|\uDD75(?:\uD83C[\uDFFB-\uDFFF]|\uFE0F)?(?:\u200D[\u2640\u2642]\uFE0F?)?|\uDE2E(?:\u200D\uD83D\uDCA8)?|\uDE35(?:\u200D\uD83D\uDCAB)?|\uDE36(?:\u200D\uD83C\uDF2B\uFE0F?)?|\uDE42(?:\u200D[\u2194\u2195]\uFE0F?)?|\uDEB6(?:\uD83C[\uDFFB-\uDFFF])?(?:\u200D(?:[\u2640\u2642]\uFE0F?(?:\u200D\u27A1\uFE0F?)?|\u27A1\uFE0F?))?)|\uD83E(?:[\uDD0C\uDD0F\uDD18-\uDD1F\uDD30-\uDD34\uDD36\uDD77\uDDB5\uDDB6\uDDBB\uDDD2\uDDD3\uDDD5\uDEC3-\uDEC5\uDEF0\uDEF2-\uDEF8](?:\uD83C[\uDFFB-\uDFFF])?|[\uDD26\uDD35\uDD37-\uDD39\uDD3C-\uDD3E\uDDB8\uDDB9\uDDCD\uDDCF\uDDD4\uDDD6-\uDDDD](?:\uD83C[\uDFFB-\uDFFF])?(?:\u200D[\u2640\u2642]\uFE0F?)?|[\uDDDE\uDDDF](?:\u200D[\u2640\u2642]\uFE0F?)?|[\uDD0D\uDD0E\uDD10-\uDD17\uDD20-\uDD25\uDD27-\uDD2F\uDD3A\uDD3F-\uDD45\uDD47-\uDD76\uDD78-\uDDB4\uDDB7\uDDBA\uDDBC-\uDDCC\uDDD0\uDDE0-\uDDFF\uDE70-\uDE7C\uDE80-\uDE8A\uDE8E-\uDEC2\uDEC6\uDEC8\uDECD-\uDEDC\uDEDF-\uDEEA\uDEEF]|\uDDCE(?:\uD83C[\uDFFB-\uDFFF])?(?:\u200D(?:[\u2640\u2642]\uFE0F?(?:\u200D\u27A1\uFE0F?)?|\u27A1\uFE0F?))?|\uDDD1(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\uD83C[\uDF3E\uDF73\uDF7C\uDF84\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3\uDE70]|\uDD1D\u200D\uD83E\uDDD1|\uDDD1\u200D\uD83E\uDDD2(?:\u200D\uD83E\uDDD2)?|\uDDD2(?:\u200D\uD83E\uDDD2)?))|\uD83C(?:\uDFFB(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D(?:\uD83D\uDC8B\u200D)?\uD83E\uDDD1\uD83C[\uDFFC-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF84\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83E\uDDD1\uD83C[\uDFFC-\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3\uDE70]|\uDD1D\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFF]|\uDEEF\u200D\uD83E\uDDD1\uD83C[\uDFFC-\uDFFF])))?|\uDFFC(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D(?:\uD83D\uDC8B\u200D)?\uD83E\uDDD1\uD83C[\uDFFB\uDFFD-\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF84\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83E\uDDD1\uD83C[\uDFFB\uDFFD-\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3\uDE70]|\uDD1D\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFF]|\uDEEF\u200D\uD83E\uDDD1\uD83C[\uDFFB\uDFFD-\uDFFF])))?|\uDFFD(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D(?:\uD83D\uDC8B\u200D)?\uD83E\uDDD1\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF84\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83E\uDDD1\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3\uDE70]|\uDD1D\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFF]|\uDEEF\u200D\uD83E\uDDD1\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF])))?|\uDFFE(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D(?:\uD83D\uDC8B\u200D)?\uD83E\uDDD1\uD83C[\uDFFB-\uDFFD\uDFFF]|\uD83C[\uDF3E\uDF73\uDF7C\uDF84\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFD\uDFFF])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3\uDE70]|\uDD1D\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFF]|\uDEEF\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFD\uDFFF])))?|\uDFFF(?:\u200D(?:[\u2695\u2696\u2708]\uFE0F?|\u2764\uFE0F?\u200D(?:\uD83D\uDC8B\u200D)?\uD83E\uDDD1\uD83C[\uDFFB-\uDFFE]|\uD83C[\uDF3E\uDF73\uDF7C\uDF84\uDF93\uDFA4\uDFA8\uDFEB\uDFED]|\uD83D(?:[\uDCBB\uDCBC\uDD27\uDD2C\uDE80\uDE92]|\uDC30\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFE])|\uD83E(?:[\uDDAF\uDDBC\uDDBD](?:\u200D\u27A1\uFE0F?)?|[\uDDB0-\uDDB3\uDE70]|\uDD1D\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFF]|\uDEEF\u200D\uD83E\uDDD1\uD83C[\uDFFB-\uDFFE])))?))?|\uDEF1(?:\uD83C(?:\uDFFB(?:\u200D\uD83E\uDEF2\uD83C[\uDFFC-\uDFFF])?|\uDFFC(?:\u200D\uD83E\uDEF2\uD83C[\uDFFB\uDFFD-\uDFFF])?|\uDFFD(?:\u200D\uD83E\uDEF2\uD83C[\uDFFB\uDFFC\uDFFE\uDFFF])?|\uDFFE(?:\u200D\uD83E\uDEF2\uD83C[\uDFFB-\uDFFD\uDFFF])?|\uDFFF(?:\u200D\uD83E\uDEF2\uD83C[\uDFFB-\uDFFE])?))?)/g;
  };
});

// node_modules/ws/lib/constants.js
var require_constants2 = __commonJS((exports, module) => {
  var BINARY_TYPES = ["nodebuffer", "arraybuffer", "fragments"];
  var hasBlob = typeof Blob !== "undefined";
  if (hasBlob)
    BINARY_TYPES.push("blob");
  module.exports = {
    BINARY_TYPES,
    CLOSE_TIMEOUT: 30000,
    EMPTY_BUFFER: Buffer.alloc(0),
    GUID: "258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
    hasBlob,
    kForOnEventAttribute: Symbol("kIsForOnEventAttribute"),
    kListener: Symbol("kListener"),
    kStatusCode: Symbol("status-code"),
    kWebSocket: Symbol("websocket"),
    NOOP: () => {}
  };
});

// node_modules/ws/lib/buffer-util.js
var require_buffer_util = __commonJS((exports, module) => {
  var { EMPTY_BUFFER } = require_constants2();
  var FastBuffer = Buffer[Symbol.species];
  function concat2(list, totalLength) {
    if (list.length === 0)
      return EMPTY_BUFFER;
    if (list.length === 1)
      return list[0];
    const target = Buffer.allocUnsafe(totalLength);
    let offset = 0;
    for (let i = 0;i < list.length; i++) {
      const buf = list[i];
      target.set(buf, offset);
      offset += buf.length;
    }
    if (offset < totalLength) {
      return new FastBuffer(target.buffer, target.byteOffset, offset);
    }
    return target;
  }
  function _mask(source, mask, output, offset, length) {
    for (let i = 0;i < length; i++) {
      output[offset + i] = source[i] ^ mask[i & 3];
    }
  }
  function _unmask(buffer, mask) {
    for (let i = 0;i < buffer.length; i++) {
      buffer[i] ^= mask[i & 3];
    }
  }
  function toArrayBuffer(buf) {
    if (buf.length === buf.buffer.byteLength) {
      return buf.buffer;
    }
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
  }
  function toBuffer(data) {
    toBuffer.readOnly = true;
    if (Buffer.isBuffer(data))
      return data;
    let buf;
    if (data instanceof ArrayBuffer) {
      buf = new FastBuffer(data);
    } else if (ArrayBuffer.isView(data)) {
      buf = new FastBuffer(data.buffer, data.byteOffset, data.byteLength);
    } else {
      buf = Buffer.from(data);
      toBuffer.readOnly = false;
    }
    return buf;
  }
  module.exports = {
    concat: concat2,
    mask: _mask,
    toArrayBuffer,
    toBuffer,
    unmask: _unmask
  };
  if (!process.env.WS_NO_BUFFER_UTIL) {
    try {
      const bufferUtil = (()=>{throw new Error("Cannot require module "+"bufferutil");})();
      module.exports.mask = function(source, mask, output, offset, length) {
        if (length < 48)
          _mask(source, mask, output, offset, length);
        else
          bufferUtil.mask(source, mask, output, offset, length);
      };
      module.exports.unmask = function(buffer, mask) {
        if (buffer.length < 32)
          _unmask(buffer, mask);
        else
          bufferUtil.unmask(buffer, mask);
      };
    } catch (e) {}
  }
});

// node_modules/ws/lib/limiter.js
var require_limiter = __commonJS((exports, module) => {
  var kDone = Symbol("kDone");
  var kRun = Symbol("kRun");

  class Limiter {
    constructor(concurrency) {
      this[kDone] = () => {
        this.pending--;
        this[kRun]();
      };
      this.concurrency = concurrency || Infinity;
      this.jobs = [];
      this.pending = 0;
    }
    add(job) {
      this.jobs.push(job);
      this[kRun]();
    }
    [kRun]() {
      if (this.pending === this.concurrency)
        return;
      if (this.jobs.length) {
        const job = this.jobs.shift();
        this.pending++;
        job(this[kDone]);
      }
    }
  }
  module.exports = Limiter;
});

// node_modules/ws/lib/permessage-deflate.js
var require_permessage_deflate = __commonJS((exports, module) => {
  var zlib = __require("zlib");
  var bufferUtil = require_buffer_util();
  var Limiter = require_limiter();
  var { kStatusCode } = require_constants2();
  var FastBuffer = Buffer[Symbol.species];
  var TRAILER = Buffer.from([0, 0, 255, 255]);
  var kPerMessageDeflate = Symbol("permessage-deflate");
  var kTotalLength = Symbol("total-length");
  var kCallback = Symbol("callback");
  var kBuffers = Symbol("buffers");
  var kError = Symbol("error");
  var zlibLimiter;

  class PerMessageDeflate {
    constructor(options) {
      this._options = options || {};
      this._threshold = this._options.threshold !== undefined ? this._options.threshold : 1024;
      this._maxPayload = this._options.maxPayload | 0;
      this._isServer = !!this._options.isServer;
      this._deflate = null;
      this._inflate = null;
      this.params = null;
      if (!zlibLimiter) {
        const concurrency = this._options.concurrencyLimit !== undefined ? this._options.concurrencyLimit : 10;
        zlibLimiter = new Limiter(concurrency);
      }
    }
    static get extensionName() {
      return "permessage-deflate";
    }
    offer() {
      const params = {};
      if (this._options.serverNoContextTakeover) {
        params.server_no_context_takeover = true;
      }
      if (this._options.clientNoContextTakeover) {
        params.client_no_context_takeover = true;
      }
      if (this._options.serverMaxWindowBits) {
        params.server_max_window_bits = this._options.serverMaxWindowBits;
      }
      if (this._options.clientMaxWindowBits) {
        params.client_max_window_bits = this._options.clientMaxWindowBits;
      } else if (this._options.clientMaxWindowBits == null) {
        params.client_max_window_bits = true;
      }
      return params;
    }
    accept(configurations) {
      configurations = this.normalizeParams(configurations);
      this.params = this._isServer ? this.acceptAsServer(configurations) : this.acceptAsClient(configurations);
      return this.params;
    }
    cleanup() {
      if (this._inflate) {
        this._inflate.close();
        this._inflate = null;
      }
      if (this._deflate) {
        const callback = this._deflate[kCallback];
        this._deflate.close();
        this._deflate = null;
        if (callback) {
          callback(new Error("The deflate stream was closed while data was being processed"));
        }
      }
    }
    acceptAsServer(offers) {
      const opts = this._options;
      const accepted = offers.find((params) => {
        if (opts.serverNoContextTakeover === false && params.server_no_context_takeover || params.server_max_window_bits && (opts.serverMaxWindowBits === false || typeof opts.serverMaxWindowBits === "number" && opts.serverMaxWindowBits > params.server_max_window_bits) || typeof opts.clientMaxWindowBits === "number" && !params.client_max_window_bits) {
          return false;
        }
        return true;
      });
      if (!accepted) {
        throw new Error("None of the extension offers can be accepted");
      }
      if (opts.serverNoContextTakeover) {
        accepted.server_no_context_takeover = true;
      }
      if (opts.clientNoContextTakeover) {
        accepted.client_no_context_takeover = true;
      }
      if (typeof opts.serverMaxWindowBits === "number") {
        accepted.server_max_window_bits = opts.serverMaxWindowBits;
      }
      if (typeof opts.clientMaxWindowBits === "number") {
        accepted.client_max_window_bits = opts.clientMaxWindowBits;
      } else if (accepted.client_max_window_bits === true || opts.clientMaxWindowBits === false) {
        delete accepted.client_max_window_bits;
      }
      return accepted;
    }
    acceptAsClient(response) {
      const params = response[0];
      if (this._options.clientNoContextTakeover === false && params.client_no_context_takeover) {
        throw new Error('Unexpected parameter "client_no_context_takeover"');
      }
      if (!params.client_max_window_bits) {
        if (typeof this._options.clientMaxWindowBits === "number") {
          params.client_max_window_bits = this._options.clientMaxWindowBits;
        }
      } else if (this._options.clientMaxWindowBits === false || typeof this._options.clientMaxWindowBits === "number" && params.client_max_window_bits > this._options.clientMaxWindowBits) {
        throw new Error('Unexpected or invalid parameter "client_max_window_bits"');
      }
      return params;
    }
    normalizeParams(configurations) {
      configurations.forEach((params) => {
        Object.keys(params).forEach((key) => {
          let value = params[key];
          if (value.length > 1) {
            throw new Error(`Parameter "${key}" must have only a single value`);
          }
          value = value[0];
          if (key === "client_max_window_bits") {
            if (value !== true) {
              const num = +value;
              if (!Number.isInteger(num) || num < 8 || num > 15) {
                throw new TypeError(`Invalid value for parameter "${key}": ${value}`);
              }
              value = num;
            } else if (!this._isServer) {
              throw new TypeError(`Invalid value for parameter "${key}": ${value}`);
            }
          } else if (key === "server_max_window_bits") {
            const num = +value;
            if (!Number.isInteger(num) || num < 8 || num > 15) {
              throw new TypeError(`Invalid value for parameter "${key}": ${value}`);
            }
            value = num;
          } else if (key === "client_no_context_takeover" || key === "server_no_context_takeover") {
            if (value !== true) {
              throw new TypeError(`Invalid value for parameter "${key}": ${value}`);
            }
          } else {
            throw new Error(`Unknown parameter "${key}"`);
          }
          params[key] = value;
        });
      });
      return configurations;
    }
    decompress(data, fin, callback) {
      zlibLimiter.add((done) => {
        this._decompress(data, fin, (err, result2) => {
          done();
          callback(err, result2);
        });
      });
    }
    compress(data, fin, callback) {
      zlibLimiter.add((done) => {
        this._compress(data, fin, (err, result2) => {
          done();
          callback(err, result2);
        });
      });
    }
    _decompress(data, fin, callback) {
      const endpoint = this._isServer ? "client" : "server";
      if (!this._inflate) {
        const key = `${endpoint}_max_window_bits`;
        const windowBits = typeof this.params[key] !== "number" ? zlib.Z_DEFAULT_WINDOWBITS : this.params[key];
        this._inflate = zlib.createInflateRaw({
          ...this._options.zlibInflateOptions,
          windowBits
        });
        this._inflate[kPerMessageDeflate] = this;
        this._inflate[kTotalLength] = 0;
        this._inflate[kBuffers] = [];
        this._inflate.on("error", inflateOnError);
        this._inflate.on("data", inflateOnData);
      }
      this._inflate[kCallback] = callback;
      this._inflate.write(data);
      if (fin)
        this._inflate.write(TRAILER);
      this._inflate.flush(() => {
        const err = this._inflate[kError];
        if (err) {
          this._inflate.close();
          this._inflate = null;
          callback(err);
          return;
        }
        const data2 = bufferUtil.concat(this._inflate[kBuffers], this._inflate[kTotalLength]);
        if (this._inflate._readableState.endEmitted) {
          this._inflate.close();
          this._inflate = null;
        } else {
          this._inflate[kTotalLength] = 0;
          this._inflate[kBuffers] = [];
          if (fin && this.params[`${endpoint}_no_context_takeover`]) {
            this._inflate.reset();
          }
        }
        callback(null, data2);
      });
    }
    _compress(data, fin, callback) {
      const endpoint = this._isServer ? "server" : "client";
      if (!this._deflate) {
        const key = `${endpoint}_max_window_bits`;
        const windowBits = typeof this.params[key] !== "number" ? zlib.Z_DEFAULT_WINDOWBITS : this.params[key];
        this._deflate = zlib.createDeflateRaw({
          ...this._options.zlibDeflateOptions,
          windowBits
        });
        this._deflate[kTotalLength] = 0;
        this._deflate[kBuffers] = [];
        this._deflate.on("data", deflateOnData);
      }
      this._deflate[kCallback] = callback;
      this._deflate.write(data);
      this._deflate.flush(zlib.Z_SYNC_FLUSH, () => {
        if (!this._deflate) {
          return;
        }
        let data2 = bufferUtil.concat(this._deflate[kBuffers], this._deflate[kTotalLength]);
        if (fin) {
          data2 = new FastBuffer(data2.buffer, data2.byteOffset, data2.length - 4);
        }
        this._deflate[kCallback] = null;
        this._deflate[kTotalLength] = 0;
        this._deflate[kBuffers] = [];
        if (fin && this.params[`${endpoint}_no_context_takeover`]) {
          this._deflate.reset();
        }
        callback(null, data2);
      });
    }
  }
  module.exports = PerMessageDeflate;
  function deflateOnData(chunk2) {
    this[kBuffers].push(chunk2);
    this[kTotalLength] += chunk2.length;
  }
  function inflateOnData(chunk2) {
    this[kTotalLength] += chunk2.length;
    if (this[kPerMessageDeflate]._maxPayload < 1 || this[kTotalLength] <= this[kPerMessageDeflate]._maxPayload) {
      this[kBuffers].push(chunk2);
      return;
    }
    this[kError] = new RangeError("Max payload size exceeded");
    this[kError].code = "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH";
    this[kError][kStatusCode] = 1009;
    this.removeListener("data", inflateOnData);
    this.reset();
  }
  function inflateOnError(err) {
    this[kPerMessageDeflate]._inflate = null;
    if (this[kError]) {
      this[kCallback](this[kError]);
      return;
    }
    err[kStatusCode] = 1007;
    this[kCallback](err);
  }
});

// node_modules/ws/lib/validation.js
var require_validation = __commonJS((exports, module) => {
  var { isUtf8 } = __require("buffer");
  var { hasBlob } = require_constants2();
  var tokenChars = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    1,
    0,
    1,
    1,
    1,
    1,
    1,
    0,
    0,
    1,
    1,
    0,
    1,
    1,
    0,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    0,
    0,
    0,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    0,
    1,
    0,
    1,
    0
  ];
  function isValidStatusCode(code) {
    return code >= 1000 && code <= 1014 && code !== 1004 && code !== 1005 && code !== 1006 || code >= 3000 && code <= 4999;
  }
  function _isValidUTF8(buf) {
    const len = buf.length;
    let i = 0;
    while (i < len) {
      if ((buf[i] & 128) === 0) {
        i++;
      } else if ((buf[i] & 224) === 192) {
        if (i + 1 === len || (buf[i + 1] & 192) !== 128 || (buf[i] & 254) === 192) {
          return false;
        }
        i += 2;
      } else if ((buf[i] & 240) === 224) {
        if (i + 2 >= len || (buf[i + 1] & 192) !== 128 || (buf[i + 2] & 192) !== 128 || buf[i] === 224 && (buf[i + 1] & 224) === 128 || buf[i] === 237 && (buf[i + 1] & 224) === 160) {
          return false;
        }
        i += 3;
      } else if ((buf[i] & 248) === 240) {
        if (i + 3 >= len || (buf[i + 1] & 192) !== 128 || (buf[i + 2] & 192) !== 128 || (buf[i + 3] & 192) !== 128 || buf[i] === 240 && (buf[i + 1] & 240) === 128 || buf[i] === 244 && buf[i + 1] > 143 || buf[i] > 244) {
          return false;
        }
        i += 4;
      } else {
        return false;
      }
    }
    return true;
  }
  function isBlob(value) {
    return hasBlob && typeof value === "object" && typeof value.arrayBuffer === "function" && typeof value.type === "string" && typeof value.stream === "function" && (value[Symbol.toStringTag] === "Blob" || value[Symbol.toStringTag] === "File");
  }
  module.exports = {
    isBlob,
    isValidStatusCode,
    isValidUTF8: _isValidUTF8,
    tokenChars
  };
  if (isUtf8) {
    module.exports.isValidUTF8 = function(buf) {
      return buf.length < 24 ? _isValidUTF8(buf) : isUtf8(buf);
    };
  } else if (!process.env.WS_NO_UTF_8_VALIDATE) {
    try {
      const isValidUTF8 = (()=>{throw new Error("Cannot require module "+"utf-8-validate");})();
      module.exports.isValidUTF8 = function(buf) {
        return buf.length < 32 ? _isValidUTF8(buf) : isValidUTF8(buf);
      };
    } catch (e) {}
  }
});

// node_modules/ws/lib/receiver.js
var require_receiver = __commonJS((exports, module) => {
  var { Writable } = __require("stream");
  var PerMessageDeflate = require_permessage_deflate();
  var {
    BINARY_TYPES,
    EMPTY_BUFFER,
    kStatusCode,
    kWebSocket
  } = require_constants2();
  var { concat: concat2, toArrayBuffer, unmask } = require_buffer_util();
  var { isValidStatusCode, isValidUTF8 } = require_validation();
  var FastBuffer = Buffer[Symbol.species];
  var GET_INFO = 0;
  var GET_PAYLOAD_LENGTH_16 = 1;
  var GET_PAYLOAD_LENGTH_64 = 2;
  var GET_MASK = 3;
  var GET_DATA = 4;
  var INFLATING = 5;
  var DEFER_EVENT = 6;

  class Receiver extends Writable {
    constructor(options = {}) {
      super();
      this._allowSynchronousEvents = options.allowSynchronousEvents !== undefined ? options.allowSynchronousEvents : true;
      this._binaryType = options.binaryType || BINARY_TYPES[0];
      this._extensions = options.extensions || {};
      this._isServer = !!options.isServer;
      this._maxBufferedChunks = options.maxBufferedChunks | 0;
      this._maxFragments = options.maxFragments | 0;
      this._maxPayload = options.maxPayload | 0;
      this._skipUTF8Validation = !!options.skipUTF8Validation;
      this[kWebSocket] = undefined;
      this._bufferedBytes = 0;
      this._buffers = [];
      this._compressed = false;
      this._payloadLength = 0;
      this._mask = undefined;
      this._fragmented = 0;
      this._masked = false;
      this._fin = false;
      this._opcode = 0;
      this._totalPayloadLength = 0;
      this._messageLength = 0;
      this._fragments = [];
      this._errored = false;
      this._loop = false;
      this._state = GET_INFO;
    }
    _write(chunk2, encoding, cb) {
      if (this._opcode === 8 && this._state == GET_INFO)
        return cb();
      if (this._maxBufferedChunks > 0 && this._buffers.length >= this._maxBufferedChunks) {
        cb(this.createError(RangeError, "Too many buffered chunks", false, 1008, "WS_ERR_TOO_MANY_BUFFERED_PARTS"));
        return;
      }
      this._bufferedBytes += chunk2.length;
      this._buffers.push(chunk2);
      this.startLoop(cb);
    }
    consume(n) {
      this._bufferedBytes -= n;
      if (n === this._buffers[0].length)
        return this._buffers.shift();
      if (n < this._buffers[0].length) {
        const buf = this._buffers[0];
        this._buffers[0] = new FastBuffer(buf.buffer, buf.byteOffset + n, buf.length - n);
        return new FastBuffer(buf.buffer, buf.byteOffset, n);
      }
      const dst = Buffer.allocUnsafe(n);
      do {
        const buf = this._buffers[0];
        const offset = dst.length - n;
        if (n >= buf.length) {
          dst.set(this._buffers.shift(), offset);
        } else {
          dst.set(new Uint8Array(buf.buffer, buf.byteOffset, n), offset);
          this._buffers[0] = new FastBuffer(buf.buffer, buf.byteOffset + n, buf.length - n);
        }
        n -= buf.length;
      } while (n > 0);
      return dst;
    }
    startLoop(cb) {
      this._loop = true;
      do {
        switch (this._state) {
          case GET_INFO:
            this.getInfo(cb);
            break;
          case GET_PAYLOAD_LENGTH_16:
            this.getPayloadLength16(cb);
            break;
          case GET_PAYLOAD_LENGTH_64:
            this.getPayloadLength64(cb);
            break;
          case GET_MASK:
            this.getMask();
            break;
          case GET_DATA:
            this.getData(cb);
            break;
          case INFLATING:
          case DEFER_EVENT:
            this._loop = false;
            return;
        }
      } while (this._loop);
      if (!this._errored)
        cb();
    }
    getInfo(cb) {
      if (this._bufferedBytes < 2) {
        this._loop = false;
        return;
      }
      const buf = this.consume(2);
      if ((buf[0] & 48) !== 0) {
        const error = this.createError(RangeError, "RSV2 and RSV3 must be clear", true, 1002, "WS_ERR_UNEXPECTED_RSV_2_3");
        cb(error);
        return;
      }
      const compressed = (buf[0] & 64) === 64;
      if (compressed && !this._extensions[PerMessageDeflate.extensionName]) {
        const error = this.createError(RangeError, "RSV1 must be clear", true, 1002, "WS_ERR_UNEXPECTED_RSV_1");
        cb(error);
        return;
      }
      this._fin = (buf[0] & 128) === 128;
      this._opcode = buf[0] & 15;
      this._payloadLength = buf[1] & 127;
      if (this._opcode === 0) {
        if (compressed) {
          const error = this.createError(RangeError, "RSV1 must be clear", true, 1002, "WS_ERR_UNEXPECTED_RSV_1");
          cb(error);
          return;
        }
        if (!this._fragmented) {
          const error = this.createError(RangeError, "invalid opcode 0", true, 1002, "WS_ERR_INVALID_OPCODE");
          cb(error);
          return;
        }
        this._opcode = this._fragmented;
      } else if (this._opcode === 1 || this._opcode === 2) {
        if (this._fragmented) {
          const error = this.createError(RangeError, `invalid opcode ${this._opcode}`, true, 1002, "WS_ERR_INVALID_OPCODE");
          cb(error);
          return;
        }
        this._compressed = compressed;
      } else if (this._opcode > 7 && this._opcode < 11) {
        if (!this._fin) {
          const error = this.createError(RangeError, "FIN must be set", true, 1002, "WS_ERR_EXPECTED_FIN");
          cb(error);
          return;
        }
        if (compressed) {
          const error = this.createError(RangeError, "RSV1 must be clear", true, 1002, "WS_ERR_UNEXPECTED_RSV_1");
          cb(error);
          return;
        }
        if (this._payloadLength > 125 || this._opcode === 8 && this._payloadLength === 1) {
          const error = this.createError(RangeError, `invalid payload length ${this._payloadLength}`, true, 1002, "WS_ERR_INVALID_CONTROL_PAYLOAD_LENGTH");
          cb(error);
          return;
        }
      } else {
        const error = this.createError(RangeError, `invalid opcode ${this._opcode}`, true, 1002, "WS_ERR_INVALID_OPCODE");
        cb(error);
        return;
      }
      if (!this._fin && !this._fragmented)
        this._fragmented = this._opcode;
      this._masked = (buf[1] & 128) === 128;
      if (this._isServer) {
        if (!this._masked) {
          const error = this.createError(RangeError, "MASK must be set", true, 1002, "WS_ERR_EXPECTED_MASK");
          cb(error);
          return;
        }
      } else if (this._masked) {
        const error = this.createError(RangeError, "MASK must be clear", true, 1002, "WS_ERR_UNEXPECTED_MASK");
        cb(error);
        return;
      }
      if (this._payloadLength === 126)
        this._state = GET_PAYLOAD_LENGTH_16;
      else if (this._payloadLength === 127)
        this._state = GET_PAYLOAD_LENGTH_64;
      else
        this.haveLength(cb);
    }
    getPayloadLength16(cb) {
      if (this._bufferedBytes < 2) {
        this._loop = false;
        return;
      }
      this._payloadLength = this.consume(2).readUInt16BE(0);
      this.haveLength(cb);
    }
    getPayloadLength64(cb) {
      if (this._bufferedBytes < 8) {
        this._loop = false;
        return;
      }
      const buf = this.consume(8);
      const num = buf.readUInt32BE(0);
      if (num > Math.pow(2, 53 - 32) - 1) {
        const error = this.createError(RangeError, "Unsupported WebSocket frame: payload length > 2^53 - 1", false, 1009, "WS_ERR_UNSUPPORTED_DATA_PAYLOAD_LENGTH");
        cb(error);
        return;
      }
      this._payloadLength = num * Math.pow(2, 32) + buf.readUInt32BE(4);
      this.haveLength(cb);
    }
    haveLength(cb) {
      if (this._payloadLength && this._opcode < 8) {
        this._totalPayloadLength += this._payloadLength;
        if (this._totalPayloadLength > this._maxPayload && this._maxPayload > 0) {
          const error = this.createError(RangeError, "Max payload size exceeded", false, 1009, "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH");
          cb(error);
          return;
        }
      }
      if (this._masked)
        this._state = GET_MASK;
      else
        this._state = GET_DATA;
    }
    getMask() {
      if (this._bufferedBytes < 4) {
        this._loop = false;
        return;
      }
      this._mask = this.consume(4);
      this._state = GET_DATA;
    }
    getData(cb) {
      let data = EMPTY_BUFFER;
      if (this._payloadLength) {
        if (this._bufferedBytes < this._payloadLength) {
          this._loop = false;
          return;
        }
        data = this.consume(this._payloadLength);
        if (this._masked && (this._mask[0] | this._mask[1] | this._mask[2] | this._mask[3]) !== 0) {
          unmask(data, this._mask);
        }
      }
      if (this._opcode > 7) {
        this.controlMessage(data, cb);
        return;
      }
      if (this._compressed) {
        this._state = INFLATING;
        this.decompress(data, cb);
        return;
      }
      if (data.length) {
        if (this._maxFragments > 0 && this._fragments.length >= this._maxFragments) {
          const error = this.createError(RangeError, "Too many message fragments", false, 1008, "WS_ERR_TOO_MANY_BUFFERED_PARTS");
          cb(error);
          return;
        }
        this._messageLength = this._totalPayloadLength;
        this._fragments.push(data);
      }
      this.dataMessage(cb);
    }
    decompress(data, cb) {
      const perMessageDeflate = this._extensions[PerMessageDeflate.extensionName];
      perMessageDeflate.decompress(data, this._fin, (err, buf) => {
        if (err)
          return cb(err);
        if (buf.length) {
          this._messageLength += buf.length;
          if (this._messageLength > this._maxPayload && this._maxPayload > 0) {
            const error = this.createError(RangeError, "Max payload size exceeded", false, 1009, "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH");
            cb(error);
            return;
          }
          if (this._maxFragments > 0 && this._fragments.length >= this._maxFragments) {
            const error = this.createError(RangeError, "Too many message fragments", false, 1008, "WS_ERR_TOO_MANY_BUFFERED_PARTS");
            cb(error);
            return;
          }
          this._fragments.push(buf);
        }
        this.dataMessage(cb);
        if (this._state === GET_INFO)
          this.startLoop(cb);
      });
    }
    dataMessage(cb) {
      if (!this._fin) {
        this._state = GET_INFO;
        return;
      }
      const messageLength = this._messageLength;
      const fragments = this._fragments;
      this._totalPayloadLength = 0;
      this._messageLength = 0;
      this._fragmented = 0;
      this._fragments = [];
      if (this._opcode === 2) {
        let data;
        if (this._binaryType === "nodebuffer") {
          data = concat2(fragments, messageLength);
        } else if (this._binaryType === "arraybuffer") {
          data = toArrayBuffer(concat2(fragments, messageLength));
        } else if (this._binaryType === "blob") {
          data = new Blob(fragments);
        } else {
          data = fragments;
        }
        if (this._allowSynchronousEvents) {
          this.emit("message", data, true);
          this._state = GET_INFO;
        } else {
          this._state = DEFER_EVENT;
          setImmediate(() => {
            this.emit("message", data, true);
            this._state = GET_INFO;
            this.startLoop(cb);
          });
        }
      } else {
        const buf = concat2(fragments, messageLength);
        if (!this._skipUTF8Validation && !isValidUTF8(buf)) {
          const error = this.createError(Error, "invalid UTF-8 sequence", true, 1007, "WS_ERR_INVALID_UTF8");
          cb(error);
          return;
        }
        if (this._state === INFLATING || this._allowSynchronousEvents) {
          this.emit("message", buf, false);
          this._state = GET_INFO;
        } else {
          this._state = DEFER_EVENT;
          setImmediate(() => {
            this.emit("message", buf, false);
            this._state = GET_INFO;
            this.startLoop(cb);
          });
        }
      }
    }
    controlMessage(data, cb) {
      if (this._opcode === 8) {
        if (data.length === 0) {
          this._loop = false;
          this.emit("conclude", 1005, EMPTY_BUFFER);
          this.end();
        } else {
          const code = data.readUInt16BE(0);
          if (!isValidStatusCode(code)) {
            const error = this.createError(RangeError, `invalid status code ${code}`, true, 1002, "WS_ERR_INVALID_CLOSE_CODE");
            cb(error);
            return;
          }
          const buf = new FastBuffer(data.buffer, data.byteOffset + 2, data.length - 2);
          if (!this._skipUTF8Validation && !isValidUTF8(buf)) {
            const error = this.createError(Error, "invalid UTF-8 sequence", true, 1007, "WS_ERR_INVALID_UTF8");
            cb(error);
            return;
          }
          this._loop = false;
          this.emit("conclude", code, buf);
          this.end();
        }
        this._state = GET_INFO;
        return;
      }
      if (this._allowSynchronousEvents) {
        this.emit(this._opcode === 9 ? "ping" : "pong", data);
        this._state = GET_INFO;
      } else {
        this._state = DEFER_EVENT;
        setImmediate(() => {
          this.emit(this._opcode === 9 ? "ping" : "pong", data);
          this._state = GET_INFO;
          this.startLoop(cb);
        });
      }
    }
    createError(ErrorCtor, message, prefix, statusCode, errorCode) {
      this._loop = false;
      this._errored = true;
      const err = new ErrorCtor(prefix ? `Invalid WebSocket frame: ${message}` : message);
      Error.captureStackTrace(err, this.createError);
      err.code = errorCode;
      err[kStatusCode] = statusCode;
      return err;
    }
  }
  module.exports = Receiver;
});

// node_modules/ws/lib/sender.js
var require_sender = __commonJS((exports, module) => {
  var { Duplex } = __require("stream");
  var { randomFillSync } = __require("crypto");
  var {
    types: { isUint8Array }
  } = __require("util");
  var PerMessageDeflate = require_permessage_deflate();
  var { EMPTY_BUFFER, kWebSocket, NOOP } = require_constants2();
  var { isBlob, isValidStatusCode } = require_validation();
  var { mask: applyMask, toBuffer } = require_buffer_util();
  var kByteLength = Symbol("kByteLength");
  var maskBuffer = Buffer.alloc(4);
  var RANDOM_POOL_SIZE = 8 * 1024;
  var randomPool;
  var randomPoolPointer = RANDOM_POOL_SIZE;
  var DEFAULT = 0;
  var DEFLATING = 1;
  var GET_BLOB_DATA = 2;

  class Sender {
    constructor(socket, extensions, generateMask) {
      this._extensions = extensions || {};
      if (generateMask) {
        this._generateMask = generateMask;
        this._maskBuffer = Buffer.alloc(4);
      }
      this._socket = socket;
      this._firstFragment = true;
      this._compress = false;
      this._bufferedBytes = 0;
      this._queue = [];
      this._state = DEFAULT;
      this.onerror = NOOP;
      this[kWebSocket] = undefined;
    }
    static frame(data, options) {
      let mask;
      let merge2 = false;
      let offset = 2;
      let skipMasking = false;
      if (options.mask) {
        mask = options.maskBuffer || maskBuffer;
        if (options.generateMask) {
          options.generateMask(mask);
        } else {
          if (randomPoolPointer === RANDOM_POOL_SIZE) {
            if (randomPool === undefined) {
              randomPool = Buffer.alloc(RANDOM_POOL_SIZE);
            }
            randomFillSync(randomPool, 0, RANDOM_POOL_SIZE);
            randomPoolPointer = 0;
          }
          mask[0] = randomPool[randomPoolPointer++];
          mask[1] = randomPool[randomPoolPointer++];
          mask[2] = randomPool[randomPoolPointer++];
          mask[3] = randomPool[randomPoolPointer++];
        }
        skipMasking = (mask[0] | mask[1] | mask[2] | mask[3]) === 0;
        offset = 6;
      }
      let dataLength;
      if (typeof data === "string") {
        if ((!options.mask || skipMasking) && options[kByteLength] !== undefined) {
          dataLength = options[kByteLength];
        } else {
          data = Buffer.from(data);
          dataLength = data.length;
        }
      } else {
        dataLength = data.length;
        merge2 = options.mask && options.readOnly && !skipMasking;
      }
      let payloadLength = dataLength;
      if (dataLength >= 65536) {
        offset += 8;
        payloadLength = 127;
      } else if (dataLength > 125) {
        offset += 2;
        payloadLength = 126;
      }
      const target = Buffer.allocUnsafe(merge2 ? dataLength + offset : offset);
      target[0] = options.fin ? options.opcode | 128 : options.opcode;
      if (options.rsv1)
        target[0] |= 64;
      target[1] = payloadLength;
      if (payloadLength === 126) {
        target.writeUInt16BE(dataLength, 2);
      } else if (payloadLength === 127) {
        target[2] = target[3] = 0;
        target.writeUIntBE(dataLength, 4, 6);
      }
      if (!options.mask)
        return [target, data];
      target[1] |= 128;
      target[offset - 4] = mask[0];
      target[offset - 3] = mask[1];
      target[offset - 2] = mask[2];
      target[offset - 1] = mask[3];
      if (skipMasking)
        return [target, data];
      if (merge2) {
        applyMask(data, mask, target, offset, dataLength);
        return [target];
      }
      applyMask(data, mask, data, 0, dataLength);
      return [target, data];
    }
    close(code, data, mask, cb) {
      let buf;
      if (code === undefined) {
        buf = EMPTY_BUFFER;
      } else if (typeof code !== "number" || !isValidStatusCode(code)) {
        throw new TypeError("First argument must be a valid error code number");
      } else if (data === undefined || !data.length) {
        buf = Buffer.allocUnsafe(2);
        buf.writeUInt16BE(code, 0);
      } else {
        const length = Buffer.byteLength(data);
        if (length > 123) {
          throw new RangeError("The message must not be greater than 123 bytes");
        }
        buf = Buffer.allocUnsafe(2 + length);
        buf.writeUInt16BE(code, 0);
        if (typeof data === "string") {
          buf.write(data, 2);
        } else if (isUint8Array(data)) {
          buf.set(data, 2);
        } else {
          throw new TypeError("Second argument must be a string or a Uint8Array");
        }
      }
      const options = {
        [kByteLength]: buf.length,
        fin: true,
        generateMask: this._generateMask,
        mask,
        maskBuffer: this._maskBuffer,
        opcode: 8,
        readOnly: false,
        rsv1: false
      };
      if (this._state !== DEFAULT) {
        this.enqueue([this.dispatch, buf, false, options, cb]);
      } else {
        this.sendFrame(Sender.frame(buf, options), cb);
      }
    }
    ping(data, mask, cb) {
      let byteLength;
      let readOnly;
      if (typeof data === "string") {
        byteLength = Buffer.byteLength(data);
        readOnly = false;
      } else if (isBlob(data)) {
        byteLength = data.size;
        readOnly = false;
      } else {
        data = toBuffer(data);
        byteLength = data.length;
        readOnly = toBuffer.readOnly;
      }
      if (byteLength > 125) {
        throw new RangeError("The data size must not be greater than 125 bytes");
      }
      const options = {
        [kByteLength]: byteLength,
        fin: true,
        generateMask: this._generateMask,
        mask,
        maskBuffer: this._maskBuffer,
        opcode: 9,
        readOnly,
        rsv1: false
      };
      if (isBlob(data)) {
        if (this._state !== DEFAULT) {
          this.enqueue([this.getBlobData, data, false, options, cb]);
        } else {
          this.getBlobData(data, false, options, cb);
        }
      } else if (this._state !== DEFAULT) {
        this.enqueue([this.dispatch, data, false, options, cb]);
      } else {
        this.sendFrame(Sender.frame(data, options), cb);
      }
    }
    pong(data, mask, cb) {
      let byteLength;
      let readOnly;
      if (typeof data === "string") {
        byteLength = Buffer.byteLength(data);
        readOnly = false;
      } else if (isBlob(data)) {
        byteLength = data.size;
        readOnly = false;
      } else {
        data = toBuffer(data);
        byteLength = data.length;
        readOnly = toBuffer.readOnly;
      }
      if (byteLength > 125) {
        throw new RangeError("The data size must not be greater than 125 bytes");
      }
      const options = {
        [kByteLength]: byteLength,
        fin: true,
        generateMask: this._generateMask,
        mask,
        maskBuffer: this._maskBuffer,
        opcode: 10,
        readOnly,
        rsv1: false
      };
      if (isBlob(data)) {
        if (this._state !== DEFAULT) {
          this.enqueue([this.getBlobData, data, false, options, cb]);
        } else {
          this.getBlobData(data, false, options, cb);
        }
      } else if (this._state !== DEFAULT) {
        this.enqueue([this.dispatch, data, false, options, cb]);
      } else {
        this.sendFrame(Sender.frame(data, options), cb);
      }
    }
    send(data, options, cb) {
      const perMessageDeflate = this._extensions[PerMessageDeflate.extensionName];
      let opcode = options.binary ? 2 : 1;
      let rsv1 = options.compress;
      let byteLength;
      let readOnly;
      if (typeof data === "string") {
        byteLength = Buffer.byteLength(data);
        readOnly = false;
      } else if (isBlob(data)) {
        byteLength = data.size;
        readOnly = false;
      } else {
        data = toBuffer(data);
        byteLength = data.length;
        readOnly = toBuffer.readOnly;
      }
      if (this._firstFragment) {
        this._firstFragment = false;
        if (rsv1 && perMessageDeflate && perMessageDeflate.params[perMessageDeflate._isServer ? "server_no_context_takeover" : "client_no_context_takeover"]) {
          rsv1 = byteLength >= perMessageDeflate._threshold;
        }
        this._compress = rsv1;
      } else {
        rsv1 = false;
        opcode = 0;
      }
      if (options.fin)
        this._firstFragment = true;
      const opts = {
        [kByteLength]: byteLength,
        fin: options.fin,
        generateMask: this._generateMask,
        mask: options.mask,
        maskBuffer: this._maskBuffer,
        opcode,
        readOnly,
        rsv1
      };
      if (isBlob(data)) {
        if (this._state !== DEFAULT) {
          this.enqueue([this.getBlobData, data, this._compress, opts, cb]);
        } else {
          this.getBlobData(data, this._compress, opts, cb);
        }
      } else if (this._state !== DEFAULT) {
        this.enqueue([this.dispatch, data, this._compress, opts, cb]);
      } else {
        this.dispatch(data, this._compress, opts, cb);
      }
    }
    getBlobData(blob, compress, options, cb) {
      this._bufferedBytes += options[kByteLength];
      this._state = GET_BLOB_DATA;
      blob.arrayBuffer().then((arrayBuffer) => {
        if (this._socket.destroyed) {
          const err = new Error("The socket was closed while the blob was being read");
          process.nextTick(callCallbacks, this, err, cb);
          return;
        }
        this._bufferedBytes -= options[kByteLength];
        const data = toBuffer(arrayBuffer);
        if (!compress) {
          this._state = DEFAULT;
          this.sendFrame(Sender.frame(data, options), cb);
          this.dequeue();
        } else {
          this.dispatch(data, compress, options, cb);
        }
      }).catch((err) => {
        process.nextTick(onError, this, err, cb);
      });
    }
    dispatch(data, compress, options, cb) {
      if (!compress) {
        this.sendFrame(Sender.frame(data, options), cb);
        return;
      }
      const perMessageDeflate = this._extensions[PerMessageDeflate.extensionName];
      this._bufferedBytes += options[kByteLength];
      this._state = DEFLATING;
      perMessageDeflate.compress(data, options.fin, (_, buf) => {
        if (this._socket.destroyed) {
          const err = new Error("The socket was closed while data was being compressed");
          callCallbacks(this, err, cb);
          return;
        }
        this._bufferedBytes -= options[kByteLength];
        this._state = DEFAULT;
        options.readOnly = false;
        this.sendFrame(Sender.frame(buf, options), cb);
        this.dequeue();
      });
    }
    dequeue() {
      while (this._state === DEFAULT && this._queue.length) {
        const params = this._queue.shift();
        this._bufferedBytes -= params[3][kByteLength];
        Reflect.apply(params[0], this, params.slice(1));
      }
    }
    enqueue(params) {
      this._bufferedBytes += params[3][kByteLength];
      this._queue.push(params);
    }
    sendFrame(list, cb) {
      if (list.length === 2) {
        this._socket.cork();
        this._socket.write(list[0]);
        this._socket.write(list[1], cb);
        this._socket.uncork();
      } else {
        this._socket.write(list[0], cb);
      }
    }
  }
  module.exports = Sender;
  function callCallbacks(sender, err, cb) {
    if (typeof cb === "function")
      cb(err);
    for (let i = 0;i < sender._queue.length; i++) {
      const params = sender._queue[i];
      const callback = params[params.length - 1];
      if (typeof callback === "function")
        callback(err);
    }
  }
  function onError(sender, err, cb) {
    callCallbacks(sender, err, cb);
    sender.onerror(err);
  }
});

// node_modules/ws/lib/event-target.js
var require_event_target = __commonJS((exports, module) => {
  var { kForOnEventAttribute, kListener } = require_constants2();
  var kCode = Symbol("kCode");
  var kData = Symbol("kData");
  var kError = Symbol("kError");
  var kMessage = Symbol("kMessage");
  var kReason = Symbol("kReason");
  var kTarget = Symbol("kTarget");
  var kType = Symbol("kType");
  var kWasClean = Symbol("kWasClean");

  class Event {
    constructor(type) {
      this[kTarget] = null;
      this[kType] = type;
    }
    get target() {
      return this[kTarget];
    }
    get type() {
      return this[kType];
    }
  }
  Object.defineProperty(Event.prototype, "target", { enumerable: true });
  Object.defineProperty(Event.prototype, "type", { enumerable: true });

  class CloseEvent extends Event {
    constructor(type, options = {}) {
      super(type);
      this[kCode] = options.code === undefined ? 0 : options.code;
      this[kReason] = options.reason === undefined ? "" : options.reason;
      this[kWasClean] = options.wasClean === undefined ? false : options.wasClean;
    }
    get code() {
      return this[kCode];
    }
    get reason() {
      return this[kReason];
    }
    get wasClean() {
      return this[kWasClean];
    }
  }
  Object.defineProperty(CloseEvent.prototype, "code", { enumerable: true });
  Object.defineProperty(CloseEvent.prototype, "reason", { enumerable: true });
  Object.defineProperty(CloseEvent.prototype, "wasClean", { enumerable: true });

  class ErrorEvent extends Event {
    constructor(type, options = {}) {
      super(type);
      this[kError] = options.error === undefined ? null : options.error;
      this[kMessage] = options.message === undefined ? "" : options.message;
    }
    get error() {
      return this[kError];
    }
    get message() {
      return this[kMessage];
    }
  }
  Object.defineProperty(ErrorEvent.prototype, "error", { enumerable: true });
  Object.defineProperty(ErrorEvent.prototype, "message", { enumerable: true });

  class MessageEvent extends Event {
    constructor(type, options = {}) {
      super(type);
      this[kData] = options.data === undefined ? null : options.data;
    }
    get data() {
      return this[kData];
    }
  }
  Object.defineProperty(MessageEvent.prototype, "data", { enumerable: true });
  var EventTarget = {
    addEventListener(type, handler, options = {}) {
      for (const listener of this.listeners(type)) {
        if (!options[kForOnEventAttribute] && listener[kListener] === handler && !listener[kForOnEventAttribute]) {
          return;
        }
      }
      let wrapper;
      if (type === "message") {
        wrapper = function onMessage(data, isBinary) {
          const event = new MessageEvent("message", {
            data: isBinary ? data : data.toString()
          });
          event[kTarget] = this;
          callListener(handler, this, event);
        };
      } else if (type === "close") {
        wrapper = function onClose(code, message) {
          const event = new CloseEvent("close", {
            code,
            reason: message.toString(),
            wasClean: this._closeFrameReceived && this._closeFrameSent
          });
          event[kTarget] = this;
          callListener(handler, this, event);
        };
      } else if (type === "error") {
        wrapper = function onError(error) {
          const event = new ErrorEvent("error", {
            error,
            message: error.message
          });
          event[kTarget] = this;
          callListener(handler, this, event);
        };
      } else if (type === "open") {
        wrapper = function onOpen() {
          const event = new Event("open");
          event[kTarget] = this;
          callListener(handler, this, event);
        };
      } else {
        return;
      }
      wrapper[kForOnEventAttribute] = !!options[kForOnEventAttribute];
      wrapper[kListener] = handler;
      if (options.once) {
        this.once(type, wrapper);
      } else {
        this.on(type, wrapper);
      }
    },
    removeEventListener(type, handler) {
      for (const listener of this.listeners(type)) {
        if (listener[kListener] === handler && !listener[kForOnEventAttribute]) {
          this.removeListener(type, listener);
          break;
        }
      }
    }
  };
  module.exports = {
    CloseEvent,
    ErrorEvent,
    Event,
    EventTarget,
    MessageEvent
  };
  function callListener(listener, thisArg, event) {
    if (typeof listener === "object" && listener.handleEvent) {
      listener.handleEvent.call(listener, event);
    } else {
      listener.call(thisArg, event);
    }
  }
});

// node_modules/ws/lib/extension.js
var require_extension = __commonJS((exports, module) => {
  var { tokenChars } = require_validation();
  function push(dest, name, elem) {
    if (dest[name] === undefined)
      dest[name] = [elem];
    else
      dest[name].push(elem);
  }
  function parse(header) {
    const offers = Object.create(null);
    let params = Object.create(null);
    let mustUnescape = false;
    let isEscaping = false;
    let inQuotes = false;
    let extensionName;
    let paramName;
    let start = -1;
    let code = -1;
    let end = -1;
    let i = 0;
    for (;i < header.length; i++) {
      code = header.charCodeAt(i);
      if (extensionName === undefined) {
        if (end === -1 && tokenChars[code] === 1) {
          if (start === -1)
            start = i;
        } else if (i !== 0 && (code === 32 || code === 9)) {
          if (end === -1 && start !== -1)
            end = i;
        } else if (code === 59 || code === 44) {
          if (start === -1) {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
          if (end === -1)
            end = i;
          const name = header.slice(start, end);
          if (code === 44) {
            push(offers, name, params);
            params = Object.create(null);
          } else {
            extensionName = name;
          }
          start = end = -1;
        } else {
          throw new SyntaxError(`Unexpected character at index ${i}`);
        }
      } else if (paramName === undefined) {
        if (end === -1 && tokenChars[code] === 1) {
          if (start === -1)
            start = i;
        } else if (code === 32 || code === 9) {
          if (end === -1 && start !== -1)
            end = i;
        } else if (code === 59 || code === 44) {
          if (start === -1) {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
          if (end === -1)
            end = i;
          push(params, header.slice(start, end), true);
          if (code === 44) {
            push(offers, extensionName, params);
            params = Object.create(null);
            extensionName = undefined;
          }
          start = end = -1;
        } else if (code === 61 && start !== -1 && end === -1) {
          paramName = header.slice(start, i);
          start = end = -1;
        } else {
          throw new SyntaxError(`Unexpected character at index ${i}`);
        }
      } else {
        if (isEscaping) {
          if (tokenChars[code] !== 1) {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
          if (start === -1)
            start = i;
          else if (!mustUnescape)
            mustUnescape = true;
          isEscaping = false;
        } else if (inQuotes) {
          if (tokenChars[code] === 1) {
            if (start === -1)
              start = i;
          } else if (code === 34 && start !== -1) {
            inQuotes = false;
            end = i;
          } else if (code === 92) {
            isEscaping = true;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        } else if (code === 34 && header.charCodeAt(i - 1) === 61) {
          inQuotes = true;
        } else if (end === -1 && tokenChars[code] === 1) {
          if (start === -1)
            start = i;
        } else if (start !== -1 && (code === 32 || code === 9)) {
          if (end === -1)
            end = i;
        } else if (code === 59 || code === 44) {
          if (start === -1) {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
          if (end === -1)
            end = i;
          let value = header.slice(start, end);
          if (mustUnescape) {
            value = value.replace(/\\/g, "");
            mustUnescape = false;
          }
          push(params, paramName, value);
          if (code === 44) {
            push(offers, extensionName, params);
            params = Object.create(null);
            extensionName = undefined;
          }
          paramName = undefined;
          start = end = -1;
        } else {
          throw new SyntaxError(`Unexpected character at index ${i}`);
        }
      }
    }
    if (start === -1 || inQuotes || code === 32 || code === 9) {
      throw new SyntaxError("Unexpected end of input");
    }
    if (end === -1)
      end = i;
    const token = header.slice(start, end);
    if (extensionName === undefined) {
      push(offers, token, params);
    } else {
      if (paramName === undefined) {
        push(params, token, true);
      } else if (mustUnescape) {
        push(params, paramName, token.replace(/\\/g, ""));
      } else {
        push(params, paramName, token);
      }
      push(offers, extensionName, params);
    }
    return offers;
  }
  function format(extensions) {
    return Object.keys(extensions).map((extension) => {
      let configurations = extensions[extension];
      if (!Array.isArray(configurations))
        configurations = [configurations];
      return configurations.map((params) => {
        return [extension].concat(Object.keys(params).map((k) => {
          let values2 = params[k];
          if (!Array.isArray(values2))
            values2 = [values2];
          return values2.map((v) => v === true ? k : `${k}=${v}`).join("; ");
        })).join("; ");
      }).join(", ");
    }).join(", ");
  }
  module.exports = { format, parse };
});

// node_modules/ws/lib/websocket.js
var require_websocket = __commonJS((exports, module) => {
  var EventEmitter = __require("events");
  var https = __require("https");
  var http = __require("http");
  var net = __require("net");
  var tls = __require("tls");
  var { randomBytes, createHash } = __require("crypto");
  var { Duplex, Readable } = __require("stream");
  var { URL } = __require("url");
  var PerMessageDeflate = require_permessage_deflate();
  var Receiver = require_receiver();
  var Sender = require_sender();
  var { isBlob } = require_validation();
  var {
    BINARY_TYPES,
    CLOSE_TIMEOUT,
    EMPTY_BUFFER,
    GUID,
    kForOnEventAttribute,
    kListener,
    kStatusCode,
    kWebSocket,
    NOOP
  } = require_constants2();
  var {
    EventTarget: { addEventListener, removeEventListener }
  } = require_event_target();
  var { format, parse } = require_extension();
  var { toBuffer } = require_buffer_util();
  var kAborted = Symbol("kAborted");
  var protocolVersions = [8, 13];
  var readyStates = ["CONNECTING", "OPEN", "CLOSING", "CLOSED"];
  var subprotocolRegex = /^[!#$%&'*+\-.0-9A-Z^_`|a-z~]+$/;

  class WebSocket extends EventEmitter {
    constructor(address, protocols, options) {
      super();
      this._binaryType = BINARY_TYPES[0];
      this._closeCode = 1006;
      this._closeFrameReceived = false;
      this._closeFrameSent = false;
      this._closeMessage = EMPTY_BUFFER;
      this._closeTimer = null;
      this._errorEmitted = false;
      this._extensions = {};
      this._paused = false;
      this._protocol = "";
      this._readyState = WebSocket.CONNECTING;
      this._receiver = null;
      this._sender = null;
      this._socket = null;
      if (address !== null) {
        this._bufferedAmount = 0;
        this._isServer = false;
        this._redirects = 0;
        if (protocols === undefined) {
          protocols = [];
        } else if (!Array.isArray(protocols)) {
          if (typeof protocols === "object" && protocols !== null) {
            options = protocols;
            protocols = [];
          } else {
            protocols = [protocols];
          }
        }
        initAsClient(this, address, protocols, options);
      } else {
        this._autoPong = options.autoPong;
        this._closeTimeout = options.closeTimeout;
        this._isServer = true;
      }
    }
    get binaryType() {
      return this._binaryType;
    }
    set binaryType(type) {
      if (!BINARY_TYPES.includes(type))
        return;
      this._binaryType = type;
      if (this._receiver)
        this._receiver._binaryType = type;
    }
    get bufferedAmount() {
      if (!this._socket)
        return this._bufferedAmount;
      return this._socket._writableState.length + this._sender._bufferedBytes;
    }
    get extensions() {
      return Object.keys(this._extensions).join();
    }
    get isPaused() {
      return this._paused;
    }
    get onclose() {
      return null;
    }
    get onerror() {
      return null;
    }
    get onopen() {
      return null;
    }
    get onmessage() {
      return null;
    }
    get protocol() {
      return this._protocol;
    }
    get readyState() {
      return this._readyState;
    }
    get url() {
      return this._url;
    }
    setSocket(socket, head3, options) {
      const receiver = new Receiver({
        allowSynchronousEvents: options.allowSynchronousEvents,
        binaryType: this.binaryType,
        extensions: this._extensions,
        isServer: this._isServer,
        maxBufferedChunks: options.maxBufferedChunks,
        maxFragments: options.maxFragments,
        maxPayload: options.maxPayload,
        skipUTF8Validation: options.skipUTF8Validation
      });
      const sender = new Sender(socket, this._extensions, options.generateMask);
      this._receiver = receiver;
      this._sender = sender;
      this._socket = socket;
      receiver[kWebSocket] = this;
      sender[kWebSocket] = this;
      socket[kWebSocket] = this;
      receiver.on("conclude", receiverOnConclude);
      receiver.on("drain", receiverOnDrain);
      receiver.on("error", receiverOnError);
      receiver.on("message", receiverOnMessage);
      receiver.on("ping", receiverOnPing);
      receiver.on("pong", receiverOnPong);
      sender.onerror = senderOnError;
      if (socket.setTimeout)
        socket.setTimeout(0);
      if (socket.setNoDelay)
        socket.setNoDelay();
      if (head3.length > 0)
        socket.unshift(head3);
      socket.on("close", socketOnClose);
      socket.on("data", socketOnData);
      socket.on("end", socketOnEnd);
      socket.on("error", socketOnError);
      this._readyState = WebSocket.OPEN;
      this.emit("open");
    }
    emitClose() {
      if (!this._socket) {
        this._readyState = WebSocket.CLOSED;
        this.emit("close", this._closeCode, this._closeMessage);
        return;
      }
      if (this._extensions[PerMessageDeflate.extensionName]) {
        this._extensions[PerMessageDeflate.extensionName].cleanup();
      }
      this._receiver.removeAllListeners();
      this._readyState = WebSocket.CLOSED;
      this.emit("close", this._closeCode, this._closeMessage);
    }
    close(code, data) {
      if (this.readyState === WebSocket.CLOSED)
        return;
      if (this.readyState === WebSocket.CONNECTING) {
        const msg = "WebSocket was closed before the connection was established";
        abortHandshake(this, this._req, msg);
        return;
      }
      if (this.readyState === WebSocket.CLOSING) {
        if (this._closeFrameSent && (this._closeFrameReceived || this._receiver._writableState.errorEmitted)) {
          this._socket.end();
        }
        return;
      }
      this._readyState = WebSocket.CLOSING;
      this._sender.close(code, data, !this._isServer, (err) => {
        if (err)
          return;
        this._closeFrameSent = true;
        if (this._closeFrameReceived || this._receiver._writableState.errorEmitted) {
          this._socket.end();
        }
      });
      setCloseTimer(this);
    }
    pause() {
      if (this.readyState === WebSocket.CONNECTING || this.readyState === WebSocket.CLOSED) {
        return;
      }
      this._paused = true;
      this._socket.pause();
    }
    ping(data, mask, cb) {
      if (this.readyState === WebSocket.CONNECTING) {
        throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
      }
      if (typeof data === "function") {
        cb = data;
        data = mask = undefined;
      } else if (typeof mask === "function") {
        cb = mask;
        mask = undefined;
      }
      if (typeof data === "number")
        data = data.toString();
      if (this.readyState !== WebSocket.OPEN) {
        sendAfterClose(this, data, cb);
        return;
      }
      if (mask === undefined)
        mask = !this._isServer;
      this._sender.ping(data || EMPTY_BUFFER, mask, cb);
    }
    pong(data, mask, cb) {
      if (this.readyState === WebSocket.CONNECTING) {
        throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
      }
      if (typeof data === "function") {
        cb = data;
        data = mask = undefined;
      } else if (typeof mask === "function") {
        cb = mask;
        mask = undefined;
      }
      if (typeof data === "number")
        data = data.toString();
      if (this.readyState !== WebSocket.OPEN) {
        sendAfterClose(this, data, cb);
        return;
      }
      if (mask === undefined)
        mask = !this._isServer;
      this._sender.pong(data || EMPTY_BUFFER, mask, cb);
    }
    resume() {
      if (this.readyState === WebSocket.CONNECTING || this.readyState === WebSocket.CLOSED) {
        return;
      }
      this._paused = false;
      if (!this._receiver._writableState.needDrain)
        this._socket.resume();
    }
    send(data, options, cb) {
      if (this.readyState === WebSocket.CONNECTING) {
        throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
      }
      if (typeof options === "function") {
        cb = options;
        options = {};
      }
      if (typeof data === "number")
        data = data.toString();
      if (this.readyState !== WebSocket.OPEN) {
        sendAfterClose(this, data, cb);
        return;
      }
      const opts = {
        binary: typeof data !== "string",
        mask: !this._isServer,
        compress: true,
        fin: true,
        ...options
      };
      if (!this._extensions[PerMessageDeflate.extensionName]) {
        opts.compress = false;
      }
      this._sender.send(data || EMPTY_BUFFER, opts, cb);
    }
    terminate() {
      if (this.readyState === WebSocket.CLOSED)
        return;
      if (this.readyState === WebSocket.CONNECTING) {
        const msg = "WebSocket was closed before the connection was established";
        abortHandshake(this, this._req, msg);
        return;
      }
      if (this._socket) {
        this._readyState = WebSocket.CLOSING;
        this._socket.destroy();
      }
    }
  }
  Object.defineProperty(WebSocket, "CONNECTING", {
    enumerable: true,
    value: readyStates.indexOf("CONNECTING")
  });
  Object.defineProperty(WebSocket.prototype, "CONNECTING", {
    enumerable: true,
    value: readyStates.indexOf("CONNECTING")
  });
  Object.defineProperty(WebSocket, "OPEN", {
    enumerable: true,
    value: readyStates.indexOf("OPEN")
  });
  Object.defineProperty(WebSocket.prototype, "OPEN", {
    enumerable: true,
    value: readyStates.indexOf("OPEN")
  });
  Object.defineProperty(WebSocket, "CLOSING", {
    enumerable: true,
    value: readyStates.indexOf("CLOSING")
  });
  Object.defineProperty(WebSocket.prototype, "CLOSING", {
    enumerable: true,
    value: readyStates.indexOf("CLOSING")
  });
  Object.defineProperty(WebSocket, "CLOSED", {
    enumerable: true,
    value: readyStates.indexOf("CLOSED")
  });
  Object.defineProperty(WebSocket.prototype, "CLOSED", {
    enumerable: true,
    value: readyStates.indexOf("CLOSED")
  });
  [
    "binaryType",
    "bufferedAmount",
    "extensions",
    "isPaused",
    "protocol",
    "readyState",
    "url"
  ].forEach((property2) => {
    Object.defineProperty(WebSocket.prototype, property2, { enumerable: true });
  });
  ["open", "error", "close", "message"].forEach((method2) => {
    Object.defineProperty(WebSocket.prototype, `on${method2}`, {
      enumerable: true,
      get() {
        for (const listener of this.listeners(method2)) {
          if (listener[kForOnEventAttribute])
            return listener[kListener];
        }
        return null;
      },
      set(handler) {
        for (const listener of this.listeners(method2)) {
          if (listener[kForOnEventAttribute]) {
            this.removeListener(method2, listener);
            break;
          }
        }
        if (typeof handler !== "function")
          return;
        this.addEventListener(method2, handler, {
          [kForOnEventAttribute]: true
        });
      }
    });
  });
  WebSocket.prototype.addEventListener = addEventListener;
  WebSocket.prototype.removeEventListener = removeEventListener;
  module.exports = WebSocket;
  function initAsClient(websocket, address, protocols, options) {
    const opts = {
      allowSynchronousEvents: true,
      autoPong: true,
      closeTimeout: CLOSE_TIMEOUT,
      protocolVersion: protocolVersions[1],
      maxBufferedChunks: 1024 * 1024,
      maxFragments: 128 * 1024,
      maxPayload: 100 * 1024 * 1024,
      skipUTF8Validation: false,
      perMessageDeflate: true,
      followRedirects: false,
      maxRedirects: 10,
      ...options,
      socketPath: undefined,
      hostname: undefined,
      protocol: undefined,
      timeout: undefined,
      method: "GET",
      host: undefined,
      path: undefined,
      port: undefined
    };
    websocket._autoPong = opts.autoPong;
    websocket._closeTimeout = opts.closeTimeout;
    if (!protocolVersions.includes(opts.protocolVersion)) {
      throw new RangeError(`Unsupported protocol version: ${opts.protocolVersion} ` + `(supported versions: ${protocolVersions.join(", ")})`);
    }
    let parsedUrl;
    if (address instanceof URL) {
      parsedUrl = address;
    } else {
      try {
        parsedUrl = new URL(address);
      } catch {
        throw new SyntaxError(`Invalid URL: ${address}`);
      }
    }
    if (parsedUrl.protocol === "http:") {
      parsedUrl.protocol = "ws:";
    } else if (parsedUrl.protocol === "https:") {
      parsedUrl.protocol = "wss:";
    }
    websocket._url = parsedUrl.href;
    const isSecure = parsedUrl.protocol === "wss:";
    const isIpcUrl = parsedUrl.protocol === "ws+unix:";
    let invalidUrlMessage;
    if (parsedUrl.protocol !== "ws:" && !isSecure && !isIpcUrl) {
      invalidUrlMessage = `The URL's protocol must be one of "ws:", "wss:", ` + '"http:", "https:", or "ws+unix:"';
    } else if (isIpcUrl && !parsedUrl.pathname) {
      invalidUrlMessage = "The URL's pathname is empty";
    } else if (parsedUrl.hash) {
      invalidUrlMessage = "The URL contains a fragment identifier";
    }
    if (invalidUrlMessage) {
      const err = new SyntaxError(invalidUrlMessage);
      if (websocket._redirects === 0) {
        throw err;
      } else {
        emitErrorAndClose(websocket, err);
        return;
      }
    }
    const defaultPort = isSecure ? 443 : 80;
    const key = randomBytes(16).toString("base64");
    const request = isSecure ? https.request : http.request;
    const protocolSet = new Set;
    let perMessageDeflate;
    opts.createConnection = opts.createConnection || (isSecure ? tlsConnect : netConnect);
    opts.defaultPort = opts.defaultPort || defaultPort;
    opts.port = parsedUrl.port || defaultPort;
    opts.host = parsedUrl.hostname.startsWith("[") ? parsedUrl.hostname.slice(1, -1) : parsedUrl.hostname;
    opts.headers = {
      ...opts.headers,
      "Sec-WebSocket-Version": opts.protocolVersion,
      "Sec-WebSocket-Key": key,
      Connection: "Upgrade",
      Upgrade: "websocket"
    };
    opts.path = parsedUrl.pathname + parsedUrl.search;
    opts.timeout = opts.handshakeTimeout;
    if (opts.perMessageDeflate) {
      perMessageDeflate = new PerMessageDeflate({
        ...opts.perMessageDeflate,
        isServer: false,
        maxPayload: opts.maxPayload
      });
      opts.headers["Sec-WebSocket-Extensions"] = format({
        [PerMessageDeflate.extensionName]: perMessageDeflate.offer()
      });
    }
    if (protocols.length) {
      for (const protocol of protocols) {
        if (typeof protocol !== "string" || !subprotocolRegex.test(protocol) || protocolSet.has(protocol)) {
          throw new SyntaxError("An invalid or duplicated subprotocol was specified");
        }
        protocolSet.add(protocol);
      }
      opts.headers["Sec-WebSocket-Protocol"] = protocols.join(",");
    }
    if (opts.origin) {
      if (opts.protocolVersion < 13) {
        opts.headers["Sec-WebSocket-Origin"] = opts.origin;
      } else {
        opts.headers.Origin = opts.origin;
      }
    }
    if (parsedUrl.username || parsedUrl.password) {
      opts.auth = `${parsedUrl.username}:${parsedUrl.password}`;
    }
    if (isIpcUrl) {
      const parts = opts.path.split(":");
      opts.socketPath = parts[0];
      opts.path = parts[1];
    }
    let req;
    if (opts.followRedirects) {
      if (websocket._redirects === 0) {
        websocket._originalIpc = isIpcUrl;
        websocket._originalSecure = isSecure;
        websocket._originalHostOrSocketPath = isIpcUrl ? opts.socketPath : parsedUrl.host;
        const headers = options && options.headers;
        options = { ...options, headers: {} };
        if (headers) {
          for (const [key2, value] of Object.entries(headers)) {
            options.headers[key2.toLowerCase()] = value;
          }
        }
      } else if (websocket.listenerCount("redirect") === 0) {
        const isSameHost = isIpcUrl ? websocket._originalIpc ? opts.socketPath === websocket._originalHostOrSocketPath : false : websocket._originalIpc ? false : parsedUrl.host === websocket._originalHostOrSocketPath;
        if (!isSameHost || websocket._originalSecure && !isSecure) {
          delete opts.headers.authorization;
          delete opts.headers.cookie;
          if (!isSameHost)
            delete opts.headers.host;
          opts.auth = undefined;
        }
      }
      if (opts.auth && !options.headers.authorization) {
        options.headers.authorization = "Basic " + Buffer.from(opts.auth).toString("base64");
      }
      req = websocket._req = request(opts);
      if (websocket._redirects) {
        websocket.emit("redirect", websocket.url, req);
      }
    } else {
      req = websocket._req = request(opts);
    }
    if (opts.timeout) {
      req.on("timeout", () => {
        abortHandshake(websocket, req, "Opening handshake has timed out");
      });
    }
    req.on("error", (err) => {
      if (req === null || req[kAborted])
        return;
      req = websocket._req = null;
      emitErrorAndClose(websocket, err);
    });
    req.on("response", (res) => {
      const location = res.headers.location;
      const statusCode = res.statusCode;
      if (location && opts.followRedirects && statusCode >= 300 && statusCode < 400) {
        if (++websocket._redirects > opts.maxRedirects) {
          abortHandshake(websocket, req, "Maximum redirects exceeded");
          return;
        }
        req.abort();
        let addr;
        try {
          addr = new URL(location, address);
        } catch (e) {
          const err = new SyntaxError(`Invalid URL: ${location}`);
          emitErrorAndClose(websocket, err);
          return;
        }
        initAsClient(websocket, addr, protocols, options);
      } else if (!websocket.emit("unexpected-response", req, res)) {
        abortHandshake(websocket, req, `Unexpected server response: ${res.statusCode}`);
      }
    });
    req.on("upgrade", (res, socket, head3) => {
      websocket.emit("upgrade", res);
      if (websocket.readyState !== WebSocket.CONNECTING)
        return;
      req = websocket._req = null;
      const upgrade = res.headers.upgrade;
      if (upgrade === undefined || upgrade.toLowerCase() !== "websocket") {
        abortHandshake(websocket, socket, "Invalid Upgrade header");
        return;
      }
      const digest = createHash("sha1").update(key + GUID).digest("base64");
      if (res.headers["sec-websocket-accept"] !== digest) {
        abortHandshake(websocket, socket, "Invalid Sec-WebSocket-Accept header");
        return;
      }
      const serverProt = res.headers["sec-websocket-protocol"];
      let protError;
      if (serverProt !== undefined) {
        if (!protocolSet.size) {
          protError = "Server sent a subprotocol but none was requested";
        } else if (!protocolSet.has(serverProt)) {
          protError = "Server sent an invalid subprotocol";
        }
      } else if (protocolSet.size) {
        protError = "Server sent no subprotocol";
      }
      if (protError) {
        abortHandshake(websocket, socket, protError);
        return;
      }
      if (serverProt)
        websocket._protocol = serverProt;
      const secWebSocketExtensions = res.headers["sec-websocket-extensions"];
      if (secWebSocketExtensions !== undefined) {
        if (!perMessageDeflate) {
          const message = "Server sent a Sec-WebSocket-Extensions header but no extension " + "was requested";
          abortHandshake(websocket, socket, message);
          return;
        }
        let extensions;
        try {
          extensions = parse(secWebSocketExtensions);
        } catch (err) {
          const message = "Invalid Sec-WebSocket-Extensions header";
          abortHandshake(websocket, socket, message);
          return;
        }
        const extensionNames = Object.keys(extensions);
        if (extensionNames.length !== 1 || extensionNames[0] !== PerMessageDeflate.extensionName) {
          const message = "Server indicated an extension that was not requested";
          abortHandshake(websocket, socket, message);
          return;
        }
        try {
          perMessageDeflate.accept(extensions[PerMessageDeflate.extensionName]);
        } catch (err) {
          const message = "Invalid Sec-WebSocket-Extensions header";
          abortHandshake(websocket, socket, message);
          return;
        }
        websocket._extensions[PerMessageDeflate.extensionName] = perMessageDeflate;
      }
      websocket.setSocket(socket, head3, {
        allowSynchronousEvents: opts.allowSynchronousEvents,
        generateMask: opts.generateMask,
        maxBufferedChunks: opts.maxBufferedChunks,
        maxFragments: opts.maxFragments,
        maxPayload: opts.maxPayload,
        skipUTF8Validation: opts.skipUTF8Validation
      });
    });
    if (opts.finishRequest) {
      opts.finishRequest(req, websocket);
    } else {
      req.end();
    }
  }
  function emitErrorAndClose(websocket, err) {
    websocket._readyState = WebSocket.CLOSING;
    websocket._errorEmitted = true;
    websocket.emit("error", err);
    websocket.emitClose();
  }
  function netConnect(options) {
    options.path = options.socketPath;
    return net.connect(options);
  }
  function tlsConnect(options) {
    options.path = undefined;
    if (!options.servername && options.servername !== "") {
      options.servername = net.isIP(options.host) ? "" : options.host;
    }
    return tls.connect(options);
  }
  function abortHandshake(websocket, stream, message) {
    websocket._readyState = WebSocket.CLOSING;
    const err = new Error(message);
    Error.captureStackTrace(err, abortHandshake);
    if (stream.setHeader) {
      stream[kAborted] = true;
      stream.abort();
      if (stream.socket && !stream.socket.destroyed) {
        stream.socket.destroy();
      }
      process.nextTick(emitErrorAndClose, websocket, err);
    } else {
      stream.destroy(err);
      stream.once("error", websocket.emit.bind(websocket, "error"));
      stream.once("close", websocket.emitClose.bind(websocket));
    }
  }
  function sendAfterClose(websocket, data, cb) {
    if (data) {
      const length = isBlob(data) ? data.size : toBuffer(data).length;
      if (websocket._socket)
        websocket._sender._bufferedBytes += length;
      else
        websocket._bufferedAmount += length;
    }
    if (cb) {
      const err = new Error(`WebSocket is not open: readyState ${websocket.readyState} ` + `(${readyStates[websocket.readyState]})`);
      process.nextTick(cb, err);
    }
  }
  function receiverOnConclude(code, reason) {
    const websocket = this[kWebSocket];
    websocket._closeFrameReceived = true;
    websocket._closeMessage = reason;
    websocket._closeCode = code;
    if (websocket._socket[kWebSocket] === undefined)
      return;
    websocket._socket.removeListener("data", socketOnData);
    process.nextTick(resume, websocket._socket);
    if (code === 1005)
      websocket.close();
    else
      websocket.close(code, reason);
  }
  function receiverOnDrain() {
    const websocket = this[kWebSocket];
    if (!websocket.isPaused)
      websocket._socket.resume();
  }
  function receiverOnError(err) {
    const websocket = this[kWebSocket];
    if (websocket._socket[kWebSocket] !== undefined) {
      websocket._socket.removeListener("data", socketOnData);
      process.nextTick(resume, websocket._socket);
      websocket.close(err[kStatusCode]);
    }
    if (!websocket._errorEmitted) {
      websocket._errorEmitted = true;
      websocket.emit("error", err);
    }
  }
  function receiverOnFinish() {
    this[kWebSocket].emitClose();
  }
  function receiverOnMessage(data, isBinary) {
    this[kWebSocket].emit("message", data, isBinary);
  }
  function receiverOnPing(data) {
    const websocket = this[kWebSocket];
    if (websocket._autoPong)
      websocket.pong(data, !this._isServer, NOOP);
    websocket.emit("ping", data);
  }
  function receiverOnPong(data) {
    this[kWebSocket].emit("pong", data);
  }
  function resume(stream) {
    stream.resume();
  }
  function senderOnError(err) {
    const websocket = this[kWebSocket];
    if (websocket.readyState === WebSocket.CLOSED)
      return;
    if (websocket.readyState === WebSocket.OPEN) {
      websocket._readyState = WebSocket.CLOSING;
      setCloseTimer(websocket);
    }
    this._socket.end();
    if (!websocket._errorEmitted) {
      websocket._errorEmitted = true;
      websocket.emit("error", err);
    }
  }
  function setCloseTimer(websocket) {
    websocket._closeTimer = setTimeout(websocket._socket.destroy.bind(websocket._socket), websocket._closeTimeout);
  }
  function socketOnClose() {
    const websocket = this[kWebSocket];
    this.removeListener("close", socketOnClose);
    this.removeListener("data", socketOnData);
    this.removeListener("end", socketOnEnd);
    websocket._readyState = WebSocket.CLOSING;
    if (!this._readableState.endEmitted && !websocket._closeFrameReceived && !websocket._receiver._writableState.errorEmitted && this._readableState.length !== 0) {
      const chunk2 = this.read(this._readableState.length);
      websocket._receiver.write(chunk2);
    }
    websocket._receiver.end();
    this[kWebSocket] = undefined;
    clearTimeout(websocket._closeTimer);
    if (websocket._receiver._writableState.finished || websocket._receiver._writableState.errorEmitted) {
      websocket.emitClose();
    } else {
      websocket._receiver.on("error", receiverOnFinish);
      websocket._receiver.on("finish", receiverOnFinish);
    }
  }
  function socketOnData(chunk2) {
    if (!this[kWebSocket]._receiver.write(chunk2)) {
      this.pause();
    }
  }
  function socketOnEnd() {
    const websocket = this[kWebSocket];
    websocket._readyState = WebSocket.CLOSING;
    websocket._receiver.end();
    this.end();
  }
  function socketOnError() {
    const websocket = this[kWebSocket];
    this.removeListener("error", socketOnError);
    this.on("error", NOOP);
    if (websocket) {
      websocket._readyState = WebSocket.CLOSING;
      this.destroy();
    }
  }
});

// node_modules/ws/lib/stream.js
var require_stream = __commonJS((exports, module) => {
  var WebSocket = require_websocket();
  var { Duplex } = __require("stream");
  function emitClose(stream) {
    stream.emit("close");
  }
  function duplexOnEnd() {
    if (!this.destroyed && this._writableState.finished) {
      this.destroy();
    }
  }
  function duplexOnError(err) {
    this.removeListener("error", duplexOnError);
    this.destroy();
    if (this.listenerCount("error") === 0) {
      this.emit("error", err);
    }
  }
  function createWebSocketStream(ws, options) {
    let terminateOnDestroy = true;
    const duplex = new Duplex({
      ...options,
      autoDestroy: false,
      emitClose: false,
      objectMode: false,
      writableObjectMode: false
    });
    ws.on("message", function message(msg, isBinary) {
      const data = !isBinary && duplex._readableState.objectMode ? msg.toString() : msg;
      if (!duplex.push(data))
        ws.pause();
    });
    ws.once("error", function error(err) {
      if (duplex.destroyed)
        return;
      terminateOnDestroy = false;
      duplex.destroy(err);
    });
    ws.once("close", function close() {
      if (duplex.destroyed)
        return;
      duplex.push(null);
    });
    duplex._destroy = function(err, callback) {
      if (ws.readyState === ws.CLOSED) {
        callback(err);
        process.nextTick(emitClose, duplex);
        return;
      }
      let called = false;
      ws.once("error", function error(err2) {
        called = true;
        callback(err2);
      });
      ws.once("close", function close() {
        if (!called)
          callback(err);
        process.nextTick(emitClose, duplex);
      });
      if (terminateOnDestroy)
        ws.terminate();
    };
    duplex._final = function(callback) {
      if (ws.readyState === ws.CONNECTING) {
        ws.once("open", function open() {
          duplex._final(callback);
        });
        return;
      }
      if (ws._socket === null)
        return;
      if (ws._socket._writableState.finished) {
        callback();
        if (duplex._readableState.endEmitted)
          duplex.destroy();
      } else {
        ws._socket.once("finish", function finish() {
          callback();
        });
        ws.close();
      }
    };
    duplex._read = function() {
      if (ws.isPaused)
        ws.resume();
    };
    duplex._write = function(chunk2, encoding, callback) {
      if (ws.readyState === ws.CONNECTING) {
        ws.once("open", function open() {
          duplex._write(chunk2, encoding, callback);
        });
        return;
      }
      ws.send(chunk2, callback);
    };
    duplex.on("end", duplexOnEnd);
    duplex.on("error", duplexOnError);
    return duplex;
  }
  module.exports = createWebSocketStream;
});

// node_modules/ws/lib/subprotocol.js
var require_subprotocol = __commonJS((exports, module) => {
  var { tokenChars } = require_validation();
  function parse(header) {
    const protocols = new Set;
    let start = -1;
    let end = -1;
    let i = 0;
    for (i;i < header.length; i++) {
      const code = header.charCodeAt(i);
      if (end === -1 && tokenChars[code] === 1) {
        if (start === -1)
          start = i;
      } else if (i !== 0 && (code === 32 || code === 9)) {
        if (end === -1 && start !== -1)
          end = i;
      } else if (code === 44) {
        if (start === -1) {
          throw new SyntaxError(`Unexpected character at index ${i}`);
        }
        if (end === -1)
          end = i;
        const protocol2 = header.slice(start, end);
        if (protocols.has(protocol2)) {
          throw new SyntaxError(`The "${protocol2}" subprotocol is duplicated`);
        }
        protocols.add(protocol2);
        start = end = -1;
      } else {
        throw new SyntaxError(`Unexpected character at index ${i}`);
      }
    }
    if (start === -1 || end !== -1) {
      throw new SyntaxError("Unexpected end of input");
    }
    const protocol = header.slice(start, i);
    if (protocols.has(protocol)) {
      throw new SyntaxError(`The "${protocol}" subprotocol is duplicated`);
    }
    protocols.add(protocol);
    return protocols;
  }
  module.exports = { parse };
});

// node_modules/ws/lib/websocket-server.js
var require_websocket_server = __commonJS((exports, module) => {
  var EventEmitter = __require("events");
  var http = __require("http");
  var { Duplex } = __require("stream");
  var { createHash } = __require("crypto");
  var extension = require_extension();
  var PerMessageDeflate = require_permessage_deflate();
  var subprotocol = require_subprotocol();
  var WebSocket = require_websocket();
  var { CLOSE_TIMEOUT, GUID, kWebSocket } = require_constants2();
  var keyRegex = /^[+/0-9A-Za-z]{22}==$/;
  var RUNNING = 0;
  var CLOSING = 1;
  var CLOSED = 2;

  class WebSocketServer extends EventEmitter {
    constructor(options, callback) {
      super();
      options = {
        allowSynchronousEvents: true,
        autoPong: true,
        maxBufferedChunks: 1024 * 1024,
        maxFragments: 128 * 1024,
        maxPayload: 100 * 1024 * 1024,
        skipUTF8Validation: false,
        perMessageDeflate: false,
        handleProtocols: null,
        clientTracking: true,
        closeTimeout: CLOSE_TIMEOUT,
        verifyClient: null,
        noServer: false,
        backlog: null,
        server: null,
        host: null,
        path: null,
        port: null,
        WebSocket,
        ...options
      };
      if (options.port == null && !options.server && !options.noServer || options.port != null && (options.server || options.noServer) || options.server && options.noServer) {
        throw new TypeError('One and only one of the "port", "server", or "noServer" options ' + "must be specified");
      }
      if (options.port != null) {
        this._server = http.createServer((req, res) => {
          const body = http.STATUS_CODES[426];
          res.writeHead(426, {
            "Content-Length": body.length,
            "Content-Type": "text/plain"
          });
          res.end(body);
        });
        this._server.listen(options.port, options.host, options.backlog, callback);
      } else if (options.server) {
        this._server = options.server;
      }
      if (this._server) {
        const emitConnection = this.emit.bind(this, "connection");
        this._removeListeners = addListeners(this._server, {
          listening: this.emit.bind(this, "listening"),
          error: this.emit.bind(this, "error"),
          upgrade: (req, socket, head3) => {
            this.handleUpgrade(req, socket, head3, emitConnection);
          }
        });
      }
      if (options.perMessageDeflate === true)
        options.perMessageDeflate = {};
      if (options.clientTracking) {
        this.clients = new Set;
        this._shouldEmitClose = false;
      }
      this.options = options;
      this._state = RUNNING;
    }
    address() {
      if (this.options.noServer) {
        throw new Error('The server is operating in "noServer" mode');
      }
      if (!this._server)
        return null;
      return this._server.address();
    }
    close(cb) {
      if (this._state === CLOSED) {
        if (cb) {
          this.once("close", () => {
            cb(new Error("The server is not running"));
          });
        }
        process.nextTick(emitClose, this);
        return;
      }
      if (cb)
        this.once("close", cb);
      if (this._state === CLOSING)
        return;
      this._state = CLOSING;
      if (this.options.noServer || this.options.server) {
        if (this._server) {
          this._removeListeners();
          this._removeListeners = this._server = null;
        }
        if (this.clients) {
          if (!this.clients.size) {
            process.nextTick(emitClose, this);
          } else {
            this._shouldEmitClose = true;
          }
        } else {
          process.nextTick(emitClose, this);
        }
      } else {
        const server = this._server;
        this._removeListeners();
        this._removeListeners = this._server = null;
        server.close(() => {
          emitClose(this);
        });
      }
    }
    shouldHandle(req) {
      if (this.options.path) {
        const index = req.url.indexOf("?");
        const pathname = index !== -1 ? req.url.slice(0, index) : req.url;
        if (pathname !== this.options.path)
          return false;
      }
      return true;
    }
    handleUpgrade(req, socket, head3, cb) {
      socket.on("error", socketOnError);
      const key = req.headers["sec-websocket-key"];
      const upgrade = req.headers.upgrade;
      const version = +req.headers["sec-websocket-version"];
      if (req.method !== "GET") {
        const message = "Invalid HTTP method";
        abortHandshakeOrEmitwsClientError(this, req, socket, 405, message);
        return;
      }
      if (upgrade === undefined || upgrade.toLowerCase() !== "websocket") {
        const message = "Invalid Upgrade header";
        abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
        return;
      }
      if (key === undefined || !keyRegex.test(key)) {
        const message = "Missing or invalid Sec-WebSocket-Key header";
        abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
        return;
      }
      if (version !== 13 && version !== 8) {
        const message = "Missing or invalid Sec-WebSocket-Version header";
        abortHandshakeOrEmitwsClientError(this, req, socket, 400, message, {
          "Sec-WebSocket-Version": "13, 8"
        });
        return;
      }
      if (!this.shouldHandle(req)) {
        abortHandshake(socket, 400);
        return;
      }
      const secWebSocketProtocol = req.headers["sec-websocket-protocol"];
      let protocols = new Set;
      if (secWebSocketProtocol !== undefined) {
        try {
          protocols = subprotocol.parse(secWebSocketProtocol);
        } catch (err) {
          const message = "Invalid Sec-WebSocket-Protocol header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
          return;
        }
      }
      const secWebSocketExtensions = req.headers["sec-websocket-extensions"];
      const extensions = {};
      if (this.options.perMessageDeflate && secWebSocketExtensions !== undefined) {
        const perMessageDeflate = new PerMessageDeflate({
          ...this.options.perMessageDeflate,
          isServer: true,
          maxPayload: this.options.maxPayload
        });
        try {
          const offers = extension.parse(secWebSocketExtensions);
          if (offers[PerMessageDeflate.extensionName]) {
            perMessageDeflate.accept(offers[PerMessageDeflate.extensionName]);
            extensions[PerMessageDeflate.extensionName] = perMessageDeflate;
          }
        } catch (err) {
          const message = "Invalid or unacceptable Sec-WebSocket-Extensions header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
          return;
        }
      }
      if (this.options.verifyClient) {
        const info = {
          origin: req.headers[`${version === 8 ? "sec-websocket-origin" : "origin"}`],
          secure: !!(req.socket.authorized || req.socket.encrypted),
          req
        };
        if (this.options.verifyClient.length === 2) {
          this.options.verifyClient(info, (verified, code, message, headers) => {
            if (!verified) {
              return abortHandshake(socket, code || 401, message, headers);
            }
            this.completeUpgrade(extensions, key, protocols, req, socket, head3, cb);
          });
          return;
        }
        if (!this.options.verifyClient(info))
          return abortHandshake(socket, 401);
      }
      this.completeUpgrade(extensions, key, protocols, req, socket, head3, cb);
    }
    completeUpgrade(extensions, key, protocols, req, socket, head3, cb) {
      if (!socket.readable || !socket.writable)
        return socket.destroy();
      if (socket[kWebSocket]) {
        throw new Error("server.handleUpgrade() was called more than once with the same " + "socket, possibly due to a misconfiguration");
      }
      if (this._state > RUNNING)
        return abortHandshake(socket, 503);
      const digest = createHash("sha1").update(key + GUID).digest("base64");
      const headers = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        `Sec-WebSocket-Accept: ${digest}`
      ];
      const ws = new this.options.WebSocket(null, undefined, this.options);
      if (protocols.size) {
        const protocol = this.options.handleProtocols ? this.options.handleProtocols(protocols, req) : protocols.values().next().value;
        if (protocol) {
          headers.push(`Sec-WebSocket-Protocol: ${protocol}`);
          ws._protocol = protocol;
        }
      }
      if (extensions[PerMessageDeflate.extensionName]) {
        const params = extensions[PerMessageDeflate.extensionName].params;
        const value = extension.format({
          [PerMessageDeflate.extensionName]: [params]
        });
        headers.push(`Sec-WebSocket-Extensions: ${value}`);
        ws._extensions = extensions;
      }
      this.emit("headers", headers, req);
      socket.write(headers.concat(`\r
`).join(`\r
`));
      socket.removeListener("error", socketOnError);
      ws.setSocket(socket, head3, {
        allowSynchronousEvents: this.options.allowSynchronousEvents,
        maxBufferedChunks: this.options.maxBufferedChunks,
        maxFragments: this.options.maxFragments,
        maxPayload: this.options.maxPayload,
        skipUTF8Validation: this.options.skipUTF8Validation
      });
      if (this.clients) {
        this.clients.add(ws);
        ws.on("close", () => {
          this.clients.delete(ws);
          if (this._shouldEmitClose && !this.clients.size) {
            process.nextTick(emitClose, this);
          }
        });
      }
      cb(ws, req);
    }
  }
  module.exports = WebSocketServer;
  function addListeners(server, map2) {
    for (const event of Object.keys(map2))
      server.on(event, map2[event]);
    return function removeListeners() {
      for (const event of Object.keys(map2)) {
        server.removeListener(event, map2[event]);
      }
    };
  }
  function emitClose(server) {
    server._state = CLOSED;
    server.emit("close");
  }
  function socketOnError() {
    this.destroy();
  }
  function abortHandshake(socket, code, message, headers) {
    message = message || http.STATUS_CODES[code];
    headers = {
      Connection: "close",
      "Content-Type": "text/html",
      "Content-Length": Buffer.byteLength(message),
      ...headers
    };
    socket.once("finish", socket.destroy);
    socket.end(`HTTP/1.1 ${code} ${http.STATUS_CODES[code]}\r
` + Object.keys(headers).map((h) => `${h}: ${headers[h]}`).join(`\r
`) + `\r
\r
` + message);
  }
  function abortHandshakeOrEmitwsClientError(server, req, socket, code, message, headers) {
    if (server.listenerCount("wsClientError")) {
      const err = new Error(message);
      Error.captureStackTrace(err, abortHandshakeOrEmitwsClientError);
      server.emit("wsClientError", err, socket, req);
    } else {
      abortHandshake(socket, code, message, headers);
    }
  }
});

// node_modules/ws/wrapper.mjs
var import_stream, import_extension, import_permessage_deflate, import_receiver, import_sender, import_subprotocol, import_websocket, import_websocket_server, wrapper_default;
var init_wrapper = __esm(() => {
  import_stream = __toESM(require_stream(), 1);
  import_extension = __toESM(require_extension(), 1);
  import_permessage_deflate = __toESM(require_permessage_deflate(), 1);
  import_receiver = __toESM(require_receiver(), 1);
  import_sender = __toESM(require_sender(), 1);
  import_subprotocol = __toESM(require_subprotocol(), 1);
  import_websocket = __toESM(require_websocket(), 1);
  import_websocket_server = __toESM(require_websocket_server(), 1);
  wrapper_default = import_websocket.default;
});

// node_modules/ink/build/devtools-window-polyfill.js
var customGlobal;
var init_devtools_window_polyfill = __esm(() => {
  init_wrapper();
  customGlobal = global;
  customGlobal.WebSocket ||= wrapper_default;
  customGlobal.window ||= global;
  customGlobal.self ||= global;
  customGlobal.window.__REACT_DEVTOOLS_COMPONENT_FILTERS__ = [
    {
      type: 1,
      value: 7,
      isEnabled: true
    },
    {
      type: 2,
      value: "InternalApp",
      isEnabled: true,
      isValid: true
    },
    {
      type: 2,
      value: "InternalAppContext",
      isEnabled: true,
      isValid: true
    },
    {
      type: 2,
      value: "InternalStdoutContext",
      isEnabled: true,
      isValid: true
    },
    {
      type: 2,
      value: "InternalStderrContext",
      isEnabled: true,
      isValid: true
    },
    {
      type: 2,
      value: "InternalStdinContext",
      isEnabled: true,
      isValid: true
    },
    {
      type: 2,
      value: "InternalFocusContext",
      isEnabled: true,
      isValid: true
    }
  ];
});

// src/devtools-stub.ts
var stub, devtools_stub_default;
var init_devtools_stub = __esm(() => {
  stub = {
    connectToDevTools() {}
  };
  devtools_stub_default = stub;
});

// node_modules/ink/build/devtools.js
var exports_devtools = {};
var init_devtools = __esm(() => {
  init_devtools_window_polyfill();
  init_devtools_stub();
  devtools_stub_default.connectToDevTools();
});

// node_modules/cli-boxes/boxes.json
var require_boxes = __commonJS((exports, module) => {
  module.exports = {
    single: {
      topLeft: "┌",
      top: "─",
      topRight: "┐",
      right: "│",
      bottomRight: "┘",
      bottom: "─",
      bottomLeft: "└",
      left: "│"
    },
    double: {
      topLeft: "╔",
      top: "═",
      topRight: "╗",
      right: "║",
      bottomRight: "╝",
      bottom: "═",
      bottomLeft: "╚",
      left: "║"
    },
    round: {
      topLeft: "╭",
      top: "─",
      topRight: "╮",
      right: "│",
      bottomRight: "╯",
      bottom: "─",
      bottomLeft: "╰",
      left: "│"
    },
    bold: {
      topLeft: "┏",
      top: "━",
      topRight: "┓",
      right: "┃",
      bottomRight: "┛",
      bottom: "━",
      bottomLeft: "┗",
      left: "┃"
    },
    singleDouble: {
      topLeft: "╓",
      top: "─",
      topRight: "╖",
      right: "║",
      bottomRight: "╜",
      bottom: "─",
      bottomLeft: "╙",
      left: "║"
    },
    doubleSingle: {
      topLeft: "╒",
      top: "═",
      topRight: "╕",
      right: "│",
      bottomRight: "╛",
      bottom: "═",
      bottomLeft: "╘",
      left: "│"
    },
    classic: {
      topLeft: "+",
      top: "-",
      topRight: "+",
      right: "|",
      bottomRight: "+",
      bottom: "-",
      bottomLeft: "+",
      left: "|"
    },
    arrow: {
      topLeft: "↘",
      top: "↓",
      topRight: "↙",
      right: "←",
      bottomRight: "↖",
      bottom: "↑",
      bottomLeft: "↗",
      left: "→"
    }
  };
});

// node_modules/cli-boxes/index.js
var require_cli_boxes = __commonJS((exports, module) => {
  var cliBoxes = require_boxes();
  module.exports = cliBoxes;
  module.exports.default = cliBoxes;
});

// node_modules/mimic-fn/index.js
var require_mimic_fn = __commonJS((exports, module) => {
  var mimicFn = (to, from) => {
    for (const prop of Reflect.ownKeys(from)) {
      Object.defineProperty(to, prop, Object.getOwnPropertyDescriptor(from, prop));
    }
    return to;
  };
  module.exports = mimicFn;
  module.exports.default = mimicFn;
});

// node_modules/onetime/index.js
var require_onetime = __commonJS((exports, module) => {
  var mimicFn = require_mimic_fn();
  var calledFunctions = new WeakMap;
  var onetime = (function_, options = {}) => {
    if (typeof function_ !== "function") {
      throw new TypeError("Expected a function");
    }
    let returnValue;
    let callCount = 0;
    const functionName = function_.displayName || function_.name || "<anonymous>";
    const onetime2 = function(...arguments_) {
      calledFunctions.set(onetime2, ++callCount);
      if (callCount === 1) {
        returnValue = function_.apply(this, arguments_);
        function_ = null;
      } else if (options.throw === true) {
        throw new Error(`Function \`${functionName}\` can only be called once`);
      }
      return returnValue;
    };
    mimicFn(onetime2, function_);
    calledFunctions.set(onetime2, callCount);
    return onetime2;
  };
  module.exports = onetime;
  module.exports.default = onetime;
  module.exports.callCount = (function_) => {
    if (!calledFunctions.has(function_)) {
      throw new Error(`The given function \`${function_.name}\` is not wrapped by the \`onetime\` package`);
    }
    return calledFunctions.get(function_);
  };
});

// node_modules/escape-string-regexp/index.js
var require_escape_string_regexp = __commonJS((exports, module) => {
  var matchOperatorsRegex = /[|\\{}()[\]^$+*?.-]/g;
  module.exports = (string) => {
    if (typeof string !== "string") {
      throw new TypeError("Expected a string");
    }
    return string.replace(matchOperatorsRegex, "\\$&");
  };
});

// node_modules/stack-utils/index.js
var require_stack_utils = __commonJS((exports, module) => {
  var escapeStringRegexp = require_escape_string_regexp();
  var cwd = typeof process === "object" && process && typeof process.cwd === "function" ? process.cwd() : ".";
  var natives = [].concat(__require("module").builtinModules, "bootstrap_node", "node").map((n) => new RegExp(`(?:\\((?:node:)?${n}(?:\\.js)?:\\d+:\\d+\\)$|^\\s*at (?:node:)?${n}(?:\\.js)?:\\d+:\\d+$)`));
  natives.push(/\((?:node:)?internal\/[^:]+:\d+:\d+\)$/, /\s*at (?:node:)?internal\/[^:]+:\d+:\d+$/, /\/\.node-spawn-wrap-\w+-\w+\/node:\d+:\d+\)?$/);

  class StackUtils {
    constructor(opts) {
      opts = {
        ignoredPackages: [],
        ...opts
      };
      if ("internals" in opts === false) {
        opts.internals = StackUtils.nodeInternals();
      }
      if ("cwd" in opts === false) {
        opts.cwd = cwd;
      }
      this._cwd = opts.cwd.replace(/\\/g, "/");
      this._internals = [].concat(opts.internals, ignoredPackagesRegExp(opts.ignoredPackages));
      this._wrapCallSite = opts.wrapCallSite || false;
    }
    static nodeInternals() {
      return [...natives];
    }
    clean(stack, indent = 0) {
      indent = " ".repeat(indent);
      if (!Array.isArray(stack)) {
        stack = stack.split(`
`);
      }
      if (!/^\s*at /.test(stack[0]) && /^\s*at /.test(stack[1])) {
        stack = stack.slice(1);
      }
      let outdent = false;
      let lastNonAtLine = null;
      const result2 = [];
      stack.forEach((st) => {
        st = st.replace(/\\/g, "/");
        if (this._internals.some((internal) => internal.test(st))) {
          return;
        }
        const isAtLine = /^\s*at /.test(st);
        if (outdent) {
          st = st.trimEnd().replace(/^(\s+)at /, "$1");
        } else {
          st = st.trim();
          if (isAtLine) {
            st = st.slice(3);
          }
        }
        st = st.replace(`${this._cwd}/`, "");
        if (st) {
          if (isAtLine) {
            if (lastNonAtLine) {
              result2.push(lastNonAtLine);
              lastNonAtLine = null;
            }
            result2.push(st);
          } else {
            outdent = true;
            lastNonAtLine = st;
          }
        }
      });
      return result2.map((line) => `${indent}${line}
`).join("");
    }
    captureString(limit, fn = this.captureString) {
      if (typeof limit === "function") {
        fn = limit;
        limit = Infinity;
      }
      const { stackTraceLimit } = Error;
      if (limit) {
        Error.stackTraceLimit = limit;
      }
      const obj = {};
      Error.captureStackTrace(obj, fn);
      const { stack } = obj;
      Error.stackTraceLimit = stackTraceLimit;
      return this.clean(stack);
    }
    capture(limit, fn = this.capture) {
      if (typeof limit === "function") {
        fn = limit;
        limit = Infinity;
      }
      const { prepareStackTrace, stackTraceLimit } = Error;
      Error.prepareStackTrace = (obj2, site) => {
        if (this._wrapCallSite) {
          return site.map(this._wrapCallSite);
        }
        return site;
      };
      if (limit) {
        Error.stackTraceLimit = limit;
      }
      const obj = {};
      Error.captureStackTrace(obj, fn);
      const { stack } = obj;
      Object.assign(Error, { prepareStackTrace, stackTraceLimit });
      return stack;
    }
    at(fn = this.at) {
      const [site] = this.capture(1, fn);
      if (!site) {
        return {};
      }
      const res = {
        line: site.getLineNumber(),
        column: site.getColumnNumber()
      };
      setFile(res, site.getFileName(), this._cwd);
      if (site.isConstructor()) {
        Object.defineProperty(res, "constructor", {
          value: true,
          configurable: true
        });
      }
      if (site.isEval()) {
        res.evalOrigin = site.getEvalOrigin();
      }
      if (site.isNative()) {
        res.native = true;
      }
      let typename;
      try {
        typename = site.getTypeName();
      } catch (_) {}
      if (typename && typename !== "Object" && typename !== "[object Object]") {
        res.type = typename;
      }
      const fname = site.getFunctionName();
      if (fname) {
        res.function = fname;
      }
      const meth = site.getMethodName();
      if (meth && fname !== meth) {
        res.method = meth;
      }
      return res;
    }
    parseLine(line) {
      const match = line && line.match(re);
      if (!match) {
        return null;
      }
      const ctor = match[1] === "new";
      let fname = match[2];
      const evalOrigin = match[3];
      const evalFile = match[4];
      const evalLine = Number(match[5]);
      const evalCol = Number(match[6]);
      let file = match[7];
      const lnum = match[8];
      const col = match[9];
      const native = match[10] === "native";
      const closeParen = match[11] === ")";
      let method2;
      const res = {};
      if (lnum) {
        res.line = Number(lnum);
      }
      if (col) {
        res.column = Number(col);
      }
      if (closeParen && file) {
        let closes = 0;
        for (let i = file.length - 1;i > 0; i--) {
          if (file.charAt(i) === ")") {
            closes++;
          } else if (file.charAt(i) === "(" && file.charAt(i - 1) === " ") {
            closes--;
            if (closes === -1 && file.charAt(i - 1) === " ") {
              const before2 = file.slice(0, i - 1);
              const after2 = file.slice(i + 1);
              file = after2;
              fname += ` (${before2}`;
              break;
            }
          }
        }
      }
      if (fname) {
        const methodMatch = fname.match(methodRe);
        if (methodMatch) {
          fname = methodMatch[1];
          method2 = methodMatch[2];
        }
      }
      setFile(res, file, this._cwd);
      if (ctor) {
        Object.defineProperty(res, "constructor", {
          value: true,
          configurable: true
        });
      }
      if (evalOrigin) {
        res.evalOrigin = evalOrigin;
        res.evalLine = evalLine;
        res.evalColumn = evalCol;
        res.evalFile = evalFile && evalFile.replace(/\\/g, "/");
      }
      if (native) {
        res.native = true;
      }
      if (fname) {
        res.function = fname;
      }
      if (method2 && fname !== method2) {
        res.method = method2;
      }
      return res;
    }
  }
  function setFile(result2, filename, cwd2) {
    if (filename) {
      filename = filename.replace(/\\/g, "/");
      if (filename.startsWith(`${cwd2}/`)) {
        filename = filename.slice(cwd2.length + 1);
      }
      result2.file = filename;
    }
  }
  function ignoredPackagesRegExp(ignoredPackages) {
    if (ignoredPackages.length === 0) {
      return [];
    }
    const packages = ignoredPackages.map((mod) => escapeStringRegexp(mod));
    return new RegExp(`[/\\\\]node_modules[/\\\\](?:${packages.join("|")})[/\\\\][^:]+:\\d+:\\d+`);
  }
  var re = new RegExp("^" + "(?:\\s*at )?" + "(?:(new) )?" + "(?:(.*?) \\()?" + "(?:eval at ([^ ]+) \\((.+?):(\\d+):(\\d+)\\), )?" + "(?:(.+?):(\\d+):(\\d+)|(native))" + "(\\)?)$");
  var methodRe = /^(.*?) \[as (.*?)\]$/;
  module.exports = StackUtils;
});

// node_modules/react/cjs/react-jsx-runtime.production.min.js
var require_react_jsx_runtime_production_min = __commonJS((exports) => {
  var f = __toESM(require_react());
  var k = Symbol.for("react.element");
  var l = Symbol.for("react.fragment");
  var m = Object.prototype.hasOwnProperty;
  var n = f.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner;
  var p = { key: true, ref: true, __self: true, __source: true };
  function q(c, a, g) {
    var b, d = {}, e = null, h = null;
    g !== undefined && (e = "" + g);
    a.key !== undefined && (e = "" + a.key);
    a.ref !== undefined && (h = a.ref);
    for (b in a)
      m.call(a, b) && !p.hasOwnProperty(b) && (d[b] = a[b]);
    if (c && c.defaultProps)
      for (b in a = c.defaultProps, a)
        d[b] === undefined && (d[b] = a[b]);
    return { $$typeof: k, type: c, key: e, ref: h, props: d, _owner: n.current };
  }
  exports.Fragment = l;
  exports.jsx = q;
  exports.jsxs = q;
});

// node_modules/react/jsx-runtime.js
var require_jsx_runtime = __commonJS((exports, module) => {
  if (true) {
    module.exports = require_react_jsx_runtime_production_min();
  } else {}
});

// node_modules/ink/build/render.js
import { Stream } from "node:stream";
import process12 from "node:process";

// node_modules/ink/build/ink.js
var import_react10 = __toESM(require_react(), 1);
import process11 from "node:process";
// node_modules/es-toolkit/dist/function/debounce.mjs
function debounce(func, debounceMs, { signal, edges } = {}) {
  let pendingThis = undefined;
  let pendingArgs = null;
  const leading = edges != null && edges.includes("leading");
  const trailing = edges == null || edges.includes("trailing");
  const invoke = () => {
    if (pendingArgs !== null) {
      func.apply(pendingThis, pendingArgs);
      pendingThis = undefined;
      pendingArgs = null;
    }
  };
  const onTimerEnd = () => {
    if (trailing) {
      invoke();
    }
    cancel();
  };
  let timeoutId = null;
  const schedule = () => {
    if (timeoutId != null) {
      clearTimeout(timeoutId);
    }
    timeoutId = setTimeout(() => {
      timeoutId = null;
      onTimerEnd();
    }, debounceMs);
  };
  const cancelTimer = () => {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  };
  const cancel = () => {
    cancelTimer();
    pendingThis = undefined;
    pendingArgs = null;
  };
  const flush = () => {
    invoke();
  };
  const debounced = function(...args) {
    if (signal?.aborted) {
      return;
    }
    pendingThis = this;
    pendingArgs = args;
    const isFirstCall = timeoutId == null;
    schedule();
    if (leading && isFirstCall) {
      invoke();
    }
  };
  debounced.schedule = schedule;
  debounced.cancel = cancel;
  debounced.flush = flush;
  signal?.addEventListener("abort", cancel, { once: true });
  return debounced;
}

// node_modules/es-toolkit/dist/compat/function/debounce.mjs
function debounce2(func, debounceMs = 0, options = {}) {
  if (typeof options !== "object") {
    options = {};
  }
  const { leading = false, trailing = true, maxWait } = options;
  const edges = Array(2);
  if (leading) {
    edges[0] = "leading";
  }
  if (trailing) {
    edges[1] = "trailing";
  }
  let result = undefined;
  let pendingAt = null;
  const _debounced = debounce(function(...args) {
    result = func.apply(this, args);
    pendingAt = null;
  }, debounceMs, { edges });
  const debounced = function(...args) {
    if (maxWait != null) {
      if (pendingAt === null) {
        pendingAt = Date.now();
      }
      if (Date.now() - pendingAt >= maxWait) {
        result = func.apply(this, args);
        pendingAt = Date.now();
        _debounced.cancel();
        _debounced.schedule();
        return result;
      }
    }
    _debounced.apply(this, args);
    return result;
  };
  const flush = () => {
    _debounced.flush();
    return result;
  };
  debounced.cancel = _debounced.cancel;
  debounced.flush = flush;
  return debounced;
}

// node_modules/es-toolkit/dist/compat/function/throttle.mjs
function throttle(func, throttleMs = 0, options = {}) {
  const { leading = true, trailing = true } = options;
  return debounce2(func, throttleMs, {
    leading,
    maxWait: throttleMs,
    trailing
  });
}
// node_modules/ansi-escapes/base.js
var exports_base = {};
__export(exports_base, {
  synchronizedOutput: () => synchronizedOutput,
  setCwd: () => setCwd,
  scrollUp: () => scrollUp,
  scrollDown: () => scrollDown,
  link: () => link,
  image: () => image,
  iTerm: () => iTerm,
  exitAlternativeScreen: () => exitAlternativeScreen,
  eraseUp: () => eraseUp,
  eraseStartLine: () => eraseStartLine,
  eraseScreen: () => eraseScreen,
  eraseLines: () => eraseLines,
  eraseLine: () => eraseLine,
  eraseEndLine: () => eraseEndLine,
  eraseDown: () => eraseDown,
  enterAlternativeScreen: () => enterAlternativeScreen,
  endSynchronizedOutput: () => endSynchronizedOutput,
  cursorUp: () => cursorUp,
  cursorTo: () => cursorTo,
  cursorShow: () => cursorShow,
  cursorSavePosition: () => cursorSavePosition,
  cursorRestorePosition: () => cursorRestorePosition,
  cursorPrevLine: () => cursorPrevLine,
  cursorNextLine: () => cursorNextLine,
  cursorMove: () => cursorMove,
  cursorLeft: () => cursorLeft,
  cursorHide: () => cursorHide,
  cursorGetPosition: () => cursorGetPosition,
  cursorForward: () => cursorForward,
  cursorDown: () => cursorDown,
  cursorBackward: () => cursorBackward,
  clearViewport: () => clearViewport,
  clearTerminal: () => clearTerminal,
  clearScreen: () => clearScreen,
  beginSynchronizedOutput: () => beginSynchronizedOutput,
  beep: () => beep,
  ConEmu: () => ConEmu
});
import process2 from "node:process";
import os from "node:os";

// node_modules/environment/index.js
var isBrowser = globalThis.window?.document !== undefined;
var isNode = globalThis.process?.versions?.node !== undefined;
var isBun = globalThis.process?.versions?.bun !== undefined;
var isDeno = globalThis.Deno?.version?.deno !== undefined;
var isElectron = globalThis.process?.versions?.electron !== undefined;
var isJsDom = globalThis.navigator?.userAgent?.includes("jsdom") === true;
var isWebWorker = typeof WorkerGlobalScope !== "undefined" && globalThis instanceof WorkerGlobalScope;
var isDedicatedWorker = typeof DedicatedWorkerGlobalScope !== "undefined" && globalThis instanceof DedicatedWorkerGlobalScope;
var isSharedWorker = typeof SharedWorkerGlobalScope !== "undefined" && globalThis instanceof SharedWorkerGlobalScope;
var isServiceWorker = typeof ServiceWorkerGlobalScope !== "undefined" && globalThis instanceof ServiceWorkerGlobalScope;
var platform = globalThis.navigator?.userAgentData?.platform;
var isMacOs = platform === "macOS" || globalThis.navigator?.platform === "MacIntel" || globalThis.navigator?.userAgent?.includes(" Mac ") === true || globalThis.process?.platform === "darwin";
var isWindows = platform === "Windows" || globalThis.navigator?.platform === "Win32" || globalThis.process?.platform === "win32";
var isLinux = platform === "Linux" || globalThis.navigator?.platform?.startsWith("Linux") === true || globalThis.navigator?.userAgent?.includes(" Linux ") === true || globalThis.process?.platform === "linux";
var isIos = platform === "iOS" || globalThis.navigator?.platform === "MacIntel" && globalThis.navigator?.maxTouchPoints > 1 || /iPad|iPhone|iPod/.test(globalThis.navigator?.platform);
var isAndroid = platform === "Android" || globalThis.navigator?.platform === "Android" || globalThis.navigator?.userAgent?.includes(" Android ") === true || globalThis.process?.platform === "android";

// node_modules/ansi-escapes/base.js
var ESC = "\x1B[";
var OSC = "\x1B]";
var BEL = "\x07";
var SEP = ";";
var isTerminalApp = !isBrowser && process2.env.TERM_PROGRAM === "Apple_Terminal";
var isWindows2 = !isBrowser && process2.platform === "win32";
var isTmux = !isBrowser && (process2.env.TERM?.startsWith("screen") || process2.env.TERM?.startsWith("tmux") || process2.env.TMUX !== undefined);
var cwdFunction = isBrowser ? () => {
  throw new Error("`process.cwd()` only works in Node.js, not the browser.");
} : process2.cwd;
var wrapOsc = (sequence) => {
  if (isTmux) {
    return "\x1BPtmux;" + sequence.replaceAll("\x1B", "\x1B\x1B") + "\x1B\\";
  }
  return sequence;
};
var cursorTo = (x, y) => {
  if (typeof x !== "number") {
    throw new TypeError("The `x` argument is required");
  }
  if (typeof y !== "number") {
    return ESC + (x + 1) + "G";
  }
  return ESC + (y + 1) + SEP + (x + 1) + "H";
};
var cursorMove = (x, y) => {
  if (typeof x !== "number") {
    throw new TypeError("The `x` argument is required");
  }
  let returnValue = "";
  if (x < 0) {
    returnValue += ESC + -x + "D";
  } else if (x > 0) {
    returnValue += ESC + x + "C";
  }
  if (y < 0) {
    returnValue += ESC + -y + "A";
  } else if (y > 0) {
    returnValue += ESC + y + "B";
  }
  return returnValue;
};
var cursorUp = (count = 1) => ESC + count + "A";
var cursorDown = (count = 1) => ESC + count + "B";
var cursorForward = (count = 1) => ESC + count + "C";
var cursorBackward = (count = 1) => ESC + count + "D";
var cursorLeft = ESC + "G";
var cursorSavePosition = isTerminalApp ? "\x1B7" : ESC + "s";
var cursorRestorePosition = isTerminalApp ? "\x1B8" : ESC + "u";
var cursorGetPosition = ESC + "6n";
var cursorNextLine = ESC + "E";
var cursorPrevLine = ESC + "F";
var cursorHide = ESC + "?25l";
var cursorShow = ESC + "?25h";
var eraseLines = (count) => {
  let clear = "";
  for (let i = 0;i < count; i++) {
    clear += eraseLine + (i < count - 1 ? cursorUp() : "");
  }
  if (count) {
    clear += cursorLeft;
  }
  return clear;
};
var eraseEndLine = ESC + "K";
var eraseStartLine = ESC + "1K";
var eraseLine = ESC + "2K";
var eraseDown = ESC + "J";
var eraseUp = ESC + "1J";
var eraseScreen = ESC + "2J";
var scrollUp = ESC + "S";
var scrollDown = ESC + "T";
var clearScreen = "\x1Bc";
var clearViewport = `${eraseScreen}${ESC}H`;
var isOldWindows = () => {
  if (isBrowser || !isWindows2) {
    return false;
  }
  const parts = os.release().split(".");
  const major = Number(parts[0]);
  const build = Number(parts[2] ?? 0);
  if (major < 10) {
    return true;
  }
  if (major === 10 && build < 10586) {
    return true;
  }
  return false;
};
var clearTerminal = isOldWindows() ? `${eraseScreen}${ESC}0f` : `${eraseScreen}${ESC}3J${ESC}H`;
var enterAlternativeScreen = ESC + "?1049h";
var exitAlternativeScreen = ESC + "?1049l";
var beginSynchronizedOutput = ESC + "?2026h";
var endSynchronizedOutput = ESC + "?2026l";
var synchronizedOutput = (text) => beginSynchronizedOutput + text + endSynchronizedOutput;
var beep = BEL;
var link = (text, url) => {
  const openLink = wrapOsc(`${OSC}8${SEP}${SEP}${url}${BEL}`);
  const closeLink = wrapOsc(`${OSC}8${SEP}${SEP}${BEL}`);
  return openLink + text + closeLink;
};
var image = (data, options = {}) => {
  let returnValue = `${OSC}1337;File=inline=1`;
  if (options.width) {
    returnValue += `;width=${options.width}`;
  }
  if (options.height) {
    returnValue += `;height=${options.height}`;
  }
  if (options.preserveAspectRatio === false) {
    returnValue += ";preserveAspectRatio=0";
  }
  const imageBuffer = Buffer.from(data);
  return wrapOsc(returnValue + `;size=${imageBuffer.byteLength}` + ":" + imageBuffer.toString("base64") + BEL);
};
var iTerm = {
  setCwd: (cwd = cwdFunction()) => wrapOsc(`${OSC}50;CurrentDir=${cwd}${BEL}`),
  annotation(message, options = {}) {
    let returnValue = `${OSC}1337;`;
    const hasX = options.x !== undefined;
    const hasY = options.y !== undefined;
    if ((hasX || hasY) && !(hasX && hasY && options.length !== undefined)) {
      throw new Error("`x`, `y` and `length` must be defined when `x` or `y` is defined");
    }
    message = message.replaceAll("|", "");
    returnValue += options.isHidden ? "AddHiddenAnnotation=" : "AddAnnotation=";
    if (options.length > 0) {
      returnValue += (hasX ? [message, options.length, options.x, options.y] : [options.length, message]).join("|");
    } else {
      returnValue += message;
    }
    return wrapOsc(returnValue + BEL);
  }
};
var ConEmu = {
  setCwd: (cwd = cwdFunction()) => wrapOsc(`${OSC}9;9;${cwd}${BEL}`)
};
var setCwd = (cwd = cwdFunction()) => iTerm.setCwd(cwd) + ConEmu.setCwd(cwd);
// node_modules/is-in-ci/index.js
import { env } from "node:process";
var isInCi = env.CI !== "0" && env.CI !== "false" && (("CI" in env) || ("CONTINUOUS_INTEGRATION" in env) || Object.keys(env).some((key) => key.startsWith("CI_")));
var is_in_ci_default = isInCi;

// node_modules/auto-bind/index.js
var getAllProperties = (object) => {
  const properties = new Set;
  do {
    for (const key of Reflect.ownKeys(object)) {
      properties.add([object, key]);
    }
  } while ((object = Reflect.getPrototypeOf(object)) && object !== Object.prototype);
  return properties;
};
function autoBind(self, { include, exclude } = {}) {
  const filter2 = (key) => {
    const match = (pattern) => typeof pattern === "string" ? key === pattern : pattern.test(key);
    if (include) {
      return include.some(match);
    }
    if (exclude) {
      return !exclude.some(match);
    }
    return true;
  };
  for (const [object, key] of getAllProperties(self.constructor.prototype)) {
    if (key === "constructor" || !filter2(key)) {
      continue;
    }
    const descriptor = Reflect.getOwnPropertyDescriptor(object, key);
    if (descriptor && typeof descriptor.value === "function") {
      self[key] = self[key].bind(self);
    }
  }
  return self;
}

// node_modules/ink/build/ink.js
var import_signal_exit2 = __toESM(require_signal_exit(), 1);

// node_modules/patch-console/dist/index.js
import { PassThrough } from "node:stream";
var consoleMethods = [
  "assert",
  "count",
  "countReset",
  "debug",
  "dir",
  "dirxml",
  "error",
  "group",
  "groupCollapsed",
  "groupEnd",
  "info",
  "log",
  "table",
  "time",
  "timeEnd",
  "timeLog",
  "trace",
  "warn"
];
var originalMethods = {};
var patchConsole = (callback) => {
  const stdout = new PassThrough;
  const stderr = new PassThrough;
  stdout.write = (data) => {
    callback("stdout", data);
  };
  stderr.write = (data) => {
    callback("stderr", data);
  };
  const internalConsole = new console.Console(stdout, stderr);
  for (const method2 of consoleMethods) {
    originalMethods[method2] = console[method2];
    console[method2] = internalConsole[method2];
  }
  return () => {
    for (const method2 of consoleMethods) {
      console[method2] = originalMethods[method2];
    }
    originalMethods = {};
  };
};
var dist_default = patchConsole;

// node_modules/yoga-layout/dist/binaries/yoga-wasm-base64-esm.js
var loadYoga = (() => {
  var _scriptDir = import.meta.url;
  return function(loadYoga2) {
    loadYoga2 = loadYoga2 || {};
    var h;
    h || (h = typeof loadYoga2 !== "undefined" ? loadYoga2 : {});
    var aa, ca;
    h.ready = new Promise(function(a, b) {
      aa = a;
      ca = b;
    });
    var da = Object.assign({}, h), q = "";
    typeof document != "undefined" && document.currentScript && (q = document.currentScript.src);
    _scriptDir && (q = _scriptDir);
    q.indexOf("blob:") !== 0 ? q = q.substr(0, q.replace(/[?#].*/, "").lastIndexOf("/") + 1) : q = "";
    var ea = h.print || console.log.bind(console), v = h.printErr || console.warn.bind(console);
    Object.assign(h, da);
    da = null;
    var w;
    h.wasmBinary && (w = h.wasmBinary);
    var noExitRuntime = h.noExitRuntime || true;
    typeof WebAssembly != "object" && x("no native wasm support detected");
    var fa, ha = false;
    function z(a, b, c) {
      c = b + c;
      for (var d = "";!(b >= c); ) {
        var e = a[b++];
        if (!e)
          break;
        if (e & 128) {
          var f = a[b++] & 63;
          if ((e & 224) == 192)
            d += String.fromCharCode((e & 31) << 6 | f);
          else {
            var g = a[b++] & 63;
            e = (e & 240) == 224 ? (e & 15) << 12 | f << 6 | g : (e & 7) << 18 | f << 12 | g << 6 | a[b++] & 63;
            65536 > e ? d += String.fromCharCode(e) : (e -= 65536, d += String.fromCharCode(55296 | e >> 10, 56320 | e & 1023));
          }
        } else
          d += String.fromCharCode(e);
      }
      return d;
    }
    var ia, ja, A, C, ka, D, E, la, ma;
    function na() {
      var a = fa.buffer;
      ia = a;
      h.HEAP8 = ja = new Int8Array(a);
      h.HEAP16 = C = new Int16Array(a);
      h.HEAP32 = D = new Int32Array(a);
      h.HEAPU8 = A = new Uint8Array(a);
      h.HEAPU16 = ka = new Uint16Array(a);
      h.HEAPU32 = E = new Uint32Array(a);
      h.HEAPF32 = la = new Float32Array(a);
      h.HEAPF64 = ma = new Float64Array(a);
    }
    var oa, pa = [], qa = [], ra = [];
    function sa() {
      var a = h.preRun.shift();
      pa.unshift(a);
    }
    var F = 0, ta = null, G = null;
    function x(a) {
      if (h.onAbort)
        h.onAbort(a);
      a = "Aborted(" + a + ")";
      v(a);
      ha = true;
      a = new WebAssembly.RuntimeError(a + ". Build with -sASSERTIONS for more info.");
      ca(a);
      throw a;
    }
    function ua(a) {
      return a.startsWith("data:application/octet-stream;base64,");
    }
    var H;
    H = "data:application/octet-stream;base64,AGFzbQEAAAABugM3YAF/AGACf38AYAF/AX9gA39/fwBgAn98AGACf38Bf2ADf39/AX9gBH9/f30BfWADf398AGAAAGAEf39/fwBgAX8BfGACf38BfGAFf39/f38Bf2AAAX9gA39/fwF9YAZ/f31/fX8AYAV/f39/fwBgAn9/AX1gBX9/f319AX1gAX8BfWADf35/AX5gB39/f39/f38AYAZ/f39/f38AYAR/f39/AX9gBn9/f319fQF9YAR/f31/AGADf399AX1gBn98f39/fwF/YAR/fHx/AGACf30AYAh/f39/f39/fwBgDX9/f39/f39/f39/f38AYAp/f39/f39/f39/AGAFf39/f38BfGAEfHx/fwF9YA1/fX1/f399fX9/f39/AX9gB39/f319f38AYAJ+fwF/YAN/fX0BfWABfAF8YAN/fHwAYAR/f319AGAHf39/fX19fQF9YA1/fX99f31/fX19fX1/AX9gC39/f39/f399fX19AX9gCH9/f39/f319AGAEf39+fgBgB39/f39/f38Bf2ACfH8BfGAFf398fH8AYAN/f38BfGAEf39/fABgA39/fQBgBn9/fX99fwF/ArUBHgFhAWEAHwFhAWIAAwFhAWMACQFhAWQAFgFhAWUAEQFhAWYAIAFhAWcAAAFhAWgAIQFhAWkAAwFhAWoAAAFhAWsAFwFhAWwACgFhAW0ABQFhAW4AAwFhAW8AAQFhAXAAFwFhAXEABgFhAXIAAAFhAXMAIgFhAXQACgFhAXUADQFhAXYAFgFhAXcAAgFhAXgAAwFhAXkAGAFhAXoAAgFhAUEAAQFhAUIAEQFhAUMAAQFhAUQAAAOiAqACAgMSBwcACRkDAAoRBgYKEwAPDxMBBiMTCgcHGgMUASQFJRQHAwMKCgMmAQYYDxobFAAKBw8KBwMDAgkCAAAFGwACBwIHBgIDAQMIDAABKAkHBQURACkZASoAAAIrLAIALQcHBy4HLwkFCgMCMA0xAgMJAgACAQYKAQIBBQEACQIFAQEABQAODQ0GFQIBHBUGAgkCEAAAAAUyDzMMBQYINAUCAwUODg41AgMCAgIDBgICNgIBDAwMAQsLCwsLCx0CAAIAAAABABABBQICAQMCEgMMCwEBAQEBAQsLAQICAwICAgICAgIDAgIICAEICAgEBAQEBAQEBAQABAQABAQEBAAE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GiABQQA2AvADIAFCADcC6AMgAigC7AMiAyACKALoAyIERwRAIAMgBGsiBEEASA0FIAEgBBAeIgM2AuwDIAEgAzYC6AMgASADIARqNgLwAyACKALoAyIEIAIoAuwDIghHBEADQCADIAQoAgA2AgAgA0EEaiEDIARBBGoiBCAIRw0ACwsgASADNgLsAwsgASACKQL0AzcC9AMgASACKAKEBDYChAQgASACKQL8AzcC/AMgAUEANgLkAwsgBSABNgIAIAEgADYC5AMLIAZBAWohBiAFQQRqIgUgB0cNAAsLDwsQAgALUAACQAJAAkACQAJAIAIOBAQAAQIDCyAAIAEgAUEwahBDDwsgACABIAFBMGogAxBEDwsgACABIAFBMGoQQg8LECQACyAAIAEgAUEwaiADEEULcAIBfwF9IwBBEGsiBCQAIARBCGogACABQQJ0QdwlaigCACACEDZDAADAfyEFAkACQAJAIAQtAAxBAWsOAgABAgsgBCoCCCEFDAELIAQqAgggA5RDCtcjPJQhBQsgBEEQaiQAIAVDAAAAACAFIAVbGwt5AgF/AX0jAEEQayIDJAAgA0EIaiAAIAFBAnRB7CVqKAIAIAIQU0MAAMB/IQQCQAJAAkAgAy0ADEEBaw4CAAECCyADKgIIIQQMAQsgAyoCCEMAAAAAlEMK1yM8lCEECyADQRBqJAAgBEMAAAAAl0MAAAAAIAQgBFsbC1QAAkACQAJAAkACQCACDgQEAAECAwsgACABIAFBwgBqEEMPCyAAIAEgAUHCAGogAxBEDwsgACABIAFBwgBqEEIPCxAkAAsgACABIAFBwgBqIAMQRQsvACAAIAJFQQF0IgIgASADEGAgACACIAEQS5IgACACIAEgAxB/IAAgAiABEFKSkgvOAQIDfwJ9IwBBEGsiAyQAQQEhBCADQQhqIABB/ABqIgUgACABQQF0akH2AGoiAS8BABAfAkACQCADKgIIIgcgAioCACIGXARAIAcgB1sEQCACLQAEIQIMAgsgBiAGXCEECyACLQAEIQIgBEUNACADLQAMIAJB/wFxRg0BCyAFIAEgBiACEDkDQCAALQAAIgFBBHENASAAIAFBBHI6AAAgACgCECIBBEAgACABEQAACyAAQYCAgP4HNgKcASAAKALkAyIADQALCyADQRBqJAALzgECA38CfSMAQRBrIgMk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AWsOAgABAgsgBCoCCCEFDAELIAQqAgggA5RDCtcjPJQhBQsgBEEQaiQAIAVDAAAAACAFIAVbGwscACAAIAFBCCACpyACQiCIpyADpyADQiCIpxAVCwUAEFgACzkAIABFBEBBAA8LAn8gAUGAf3FBgL8DRiABQf8ATXJFBEBB/DtBGTYCAEF/DAELIAAgAToAAEEBCwvEAgACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQCABQQlrDhIACgsMCgsCAwQFDAsMDAoLBwgJCyACIAIoAgAiAUEEajYCACAAIAEoAgA2AgAPCwALIAIgAigCACIBQQRqNgIAIAAgATIBADcDAA8LIAIgAigCACIBQQRqNgIAIAAgATMBADcDAA8LIAIgAigCACIBQQRqNgIAIAAgATAAADcDAA8LIAIgAigCACIBQQRqNgIAIAAgATEAADcDAA8LAAsgAiACKAIAQQdqQXhxIgFBCGo2AgAgACABKwMAOQMADwsgACACIAMRAQALDwsgAiACKAIAIgFBBGo2AgAgACABNAIANwMADwsgAiACKAIAIgFBBGo2AgAgACABNQIANwMADwsgAiACKAIAQQdqQXhxIgFBCGo2AgAgACABKQMANwMAC84BAgN/An0jAEEQayIDJABBASEEIANBCGogAEH8AGoiBSAAIAFBAXRqQegAaiIBLwEAEB8CQAJAIAMqAggiByACKgIAIgZcBEAgByAHWwRAIAItAAQhAgwCCyAGIAZcIQQLIAItAAQhAiAERQ0AIAMtAAwgAkH/AXFGDQELIAUgASAGIAIQOQNAIAAtAAAiAUEEcQ0BIAAgAUEEcjoAACAAKAIQIgEEQCAAIAERAAALIABBgICA/gc2ApwBIAAoAuQDIgANAAsLIANBEGokAAtdAQR/IAAoAgAhAgNAIAIsAAAiAxBXBEBBfyEEIAAgAkEBaiICNgIAIAFBzJmz5gBNBH9BfyADQTBrIgMgAUEKbCIEaiADIARB/////wdzShsFIAQLIQEMAQsLIAELrhQCEn8BfiMAQdAAayIIJAAgCCABNgJMIAhBN2ohFyAIQThqIRQCQAJAAkACQANAIAEhDSAHIA5B/////wdzSg0BIAcgDmohDgJAAkACQCANIgctAAAiCQRAA0ACQAJAIAlB/wFxIgFFBEAgByEBDAELIAFBJUcNASAHIQkDQCAJLQABQSVHBEAgCSEBDAILIAdBAWohByAJLQACIQogCUECaiIBIQkgCkElRg0ACwsgByANayIHIA5B/////wdzIhhKDQcgAARAIAAgDSAHECYLIAcNBiAIIAE2AkwgAUEBaiEHQX8hEgJAIAEsAAEiChBXRQ0AIAEtAAJBJEcNACABQQNqIQcgCkEwayESQQEhFQsgCCAHNgJMQQAhDAJAIAcsAAAiCUEgayIBQR9LBEAgByEKDAELIAchCkEBIAF0IgFBidEEcUUNAANAIAggB0EBaiIKNgJMIAEgDHIhDCAHLAABIglBIGsiAUEgTw0BIAohB0EBIAF0IgFBidEEcQ0ACwsCQCAJQSpGBEACfwJAIAosAAEiARBXRQ0AIAotAAJBJEcNACABQQJ0IARqQcABa0EKNgIAIApBA2ohCUEBIRUgCiwAAUEDdCADakGAA2soAgAMAQsgFQ0GIApBAWohCSAARQRAIAggCTYCTEEAIRVBACETDAMLIAIgAigCACIBQQRqNgIAQQAhFSABKAIACyETIAggCTYCTCATQQBODQFBACATayETIAxBgMAAciEMDAELIAhBzABqEIkBIhNBAEgNCCAIKAJMIQkLQQAhB0F/IQsCfyAJLQAAQS5HBEAgCSEBQQAMAQsgCS0AAUEqRgRAAn8CQCAJLAACIgEQV0UNACAJLQADQSRHDQAgAUECdCAEakHAAWtBCjYCACAJQQRqIQEgCSwAAkEDdCADakGAA2soAgAMAQsgFQ0GIAlBAmohAUEAIABFDQAaIAIgAigCACIKQQRqNgIAIAooAgALIQsgCCABNgJMIAtBf3NBH3YMAQsgCCAJQQFqNgJMIAhBzABqEIkBIQsgCCgCTCEBQQELIQ8DQCAHIRFBHCEKIAEiECwAACIHQfsAa0FGSQ0JIBBBAWohASAHIBFBOmxqQf8qai0AACIHQQFrQQhJDQALIAggATYCTAJAAkAgB0EbRwRAIAdFDQsgEkEATgRAIAQgEkECdGogBzYCACAIIAMgEkEDdGopAwA3A0AMAgsgAEUNCCAIQUBrIAcgAiAGEIcBDAILIBJBAE4NCgtBACEHIABFDQcLIAxB//97cSIJIAwgDEGAwABxGyEMQQAhEkGPCSEWIBQhCgJAAkACQAJ/AkACQAJAAkACfwJAAkACQAJAAkACQAJAIBAsAAAiB0FfcSAHIAdBD3FBA0YbIAcgERsiB0HYAGsOIQQUFBQUFBQUFA4UDwYODg4UBhQUFBQCBQMUFAkUARQUBAALAkAgB0HBAGsOBw4UCxQODg4ACyAHQdMARg0JDBMLIAgpA0AhGUGPCQwFC0EAIQcCQAJAAkACQAJAAkACQCARQf8BcQ4IAAECAwQaBQYaCyAIKAJAIA42AgAMGQsgCCgCQCAONgIADBgLIAgoAkAgDqw3AwAMFwsgCCgCQCAOOwEADBYLIAgoAkAgDjoAAAwVCyAIKAJAIA42AgAMFAsgCCgCQCAOrDcDAAwTC0EIIAsgC0EITRshCyAMQQhyIQxB+AAhBwsgFCENIAgpA0AiGVBFBEAgB0EgcSEQA0AgDUEBayINIBmnQQ9xQZAvai0AACAQcjoAACAZQg9WIQkgGUIEiCEZIAkNAAsLIAxBCHFFIAgpA0BQcg0DIAdBBHZBjwlqIRZBAiESDAMLIBQhByAIKQNAIhlQRQRAA0AgB0EBayIHIBmnQQdxQTByOgAAIBlCB1YhDSAZQgOIIRkgDQ0ACwsgByENIAxBCHFFDQIgCyAUIA1rIgdBAWogByALSBshCwwCCyAIKQNAIhlCAFMEQCAIQgAgGX0iGTcDQEEBIRJBjwkMAQsgDEGAEHEEQEEBIRJBkAkMAQtBkQlBjwkgDEEBcSISGwshFiAZIBQQRyENCyAPQQAgC0EASBsNDiAMQf//e3EgDCAPGyEMIAgpA0AiGUIAUiALckUEQCAUIQ1BACELDAwLIAsgGVAgFCANa2oiByAHIAtIGyELDAsLQQAhDAJ/Qf////8HIAsgC0H/////B08bIgoiEUEARyEQAkACfwJAAkAgCCgCQCIHQY4lIAcbIg0iD0EDcUUgEUVyDQADQCAPLQAAIgxFDQIgEUEBayIRQQBHIRAgD0EBaiIPQQNxRQ0BIBENAAsLIBBFDQICQCAPLQAARSARQQRJckUEQANAIA8oAgAiB0F/cyAHQYGChAhrcUGAgYKEeHENAiAPQQRqIQ8gEUEEayIRQQNLDQALCyARRQ0DC0EADAELQQELIRADQCAQRQRAIA8tAAAhDEEBIRAMAQsgDyAMRQ0CGiAPQQFqIQ8gEUEBayIRRQ0BQQAhEAwACwALQQALIgcgDWsgCiAHGyIHIA1qIQogC0EATgRAIAkhDCAHIQsMCwsgCSEMIAchCyAKLQAADQ0MCgsgCwRAIAgoAkAMAgtBACEHIABBICATQQAgDBApDAILIAhBADYCDCAIIAgpA0A+AgggCCAIQQhqIgc2AkBBfyELIAcLIQlBACEHAkADQCAJKAIAIg1FDQEgCEEEaiANEIYBIgpBAEgiDSAKIAsgB2tLckUEQCAJQQRqIQkgCyAHIApqIgdLDQEMAgsLIA0NDQtBPSEKIAdBAEgNCyAAQSAgEyAHIAwQKSAHRQRAQQAhBwwBC0EAIQogCCgCQCEJA0AgCSgCACINRQ0BIAhBBGogDRCGASINIApqIgogB0sNASAAIAhBBGogDRAmIAlBBGohCSAHIApLDQALCyAAQSAgEyAHIAxBgMAAcxApIBMgByAHIBNIGyEHDAgLIA9BACALQQBIGw0IQT0hCiAAIAgrA0AgEyALIAwgByAFERwAIgdBAE4NBwwJCyAIIAgpA0A8ADdBASELIBchDSAJIQwMBAsgBy0AASEJIAdBAWohBwwACwALIAANByAVRQ0CQQEhBwNAIAQgB0ECdGooAgAiAARAIAMgB0EDdGogACACIAYQhwFBASEOIAdBAWoiB0EKRw0BDAkLC0EBIQ4gB0EKTw0HA0AgBCAHQQJ0aigCAA0BIAdBAWoiB0EKRw0ACwwHC0EcIQoMBAsgCyAKIA1rIhAgCyAQShsiCSASQf////8Hc0oNAkE9IQogEyAJIBJqIgsgCyATSBsiByAYSg0DIABBICAHIAsgDBApIAAgFiASECYgAEEwIAcgCyAMQYCABHMQKSAAQTAgCSAQQQAQKSAAIA0gEBAmIABBICAHIAsgDEGAwABzECkMAQsLQQAhDgwDC0E9IQoLQfw7IAo2AgALQX8hDgsgCEHQAGokACAOC9kCAQR/IwBB0AFrIgUkACAFIAI2AswBIAVBoAFqIgJBAEEoECoaIAUgBSgCzAE2AsgBAkBBACABIAVByAFqIAVB0ABqIAIgAyAEEIoBQQBIBEBBfyEEDAELQQEgBiAAKAJMQQBOGyEGIAAoAgAhByAAKAJIQQBMBEAgACAHQV9xNgIACwJ/AkACQCAAKAIwRQRAIABB0AA2AjAgAEEANgIcIABCADcDECAAKAIsIQggACAFNgIsDAELIAAoAhANAQtBfyAAEJ0BDQEaCyAAIAEgBUHIAWogBUHQAGogBUGgAWogAyAEEIoBCyECIAgEQCAAQQBBACAAKAIkEQYAGiAAQQA2AjAgACAINgIsIABBADYCHCAAKAIUIQEgAEIANwMQIAJBfyABGyECCyAAIAAoAgAiACAHQSBxcjYCAEF/IAIgAEEgcRshBCAGRQ0ACyAFQdABaiQAIAQLfwIBfwF+IAC9IgNCNIinQf8PcSICQf8PRwR8IAJFBEAgASAARAAAAAAAAAAAYQR/QQAFIABEAAAAAAAA8EOiIAEQjAEhACABKAIAQUBqCzYCACAADwsgASACQf4HazYCACADQv////////+HgH+DQoCAgICAgIDwP4S/BSAACwsVACAARQRAQQAPC0H8OyAANgIAQX8LzgECA38CfSMAQRBrIgMkAEEBIQQgA0EIaiAAQfwAaiIFIAAgAUEBdGpBxABqIgEvAQAQHwJAAkAgAyoCCCIHIAIqAgAiBlwEQCAHIAdbBEAgAi0ABCECDAILIAYgBlwhBAsgAi0ABCECIARFDQAgAy0ADCACQf8BcUYNAQsgBSABIAYgAhA5A0AgAC0AACIBQQRxDQEgACABQQRyOgAAIAAoAhAiAQRAIAAgAREAAAsgAEGAgID+BzYCnAEgACgC5AMiAA0ACwsgA0EQaiQAC9EDAEHUO0GoHBAcQdU7QYoWQQFBAUEAEBtB1jtB/RJBAUGAf0H/ABAEQdc7QfYSQQFBgH9B/wAQBEHYO0H0EkEBQQBB/wEQBEHZO0GUCkECQYCAfkH//wEQBEHaO0GLCkECQQBB//8DEARB2ztBsQpBBEGAgICAeEH/////BxAEQdw7QagKQQRBAEF/EARB3TtB+BhBBEGAgICAeEH/////BxAEQd47Qe8YQQRBAEF/EARB3ztBjxBCgICAgICAgICAf0L///////////8AEIQBQeA7QY4QQgBCfxCEAUHhO0GIEEEEEA1B4jtB9BtBCBANQeM7QaQZEA5B5DtBmSIQDkHlO0EEQZcZEAhB5jtBAkGwGRAIQec7QQRBvxkQCEHoO0GPFhAaQek7QQBB1CEQAUHqO0EAQboiEAFB6ztBAUHyIRABQew7QQJB5B4QAUHtO0EDQYMfEAFB7jtBBEGrHxABQe87QQVByB8QAUHwO0EEQd8iEAFB8TtBBUH9IhABQeo7QQBBriAQAUHrO0EBQY0gEAFB7DtBAkHwIBABQe07QQNBziAQAUHuO0EEQbMhEAFB7ztBBUGRIRABQfI7QQZB7h8QAUHzO0EHQaQjEAELJQAgAEH0JjYCACAALQAEBEAgACgCCEH9DxBmCyAAKAIIEAYgAAsDAAALJQAgAEHsJzYCACAALQAEBEAgACgCCEH9DxBmCyAAKAIIEAYgAAs3AQJ/QQQQHiICIAE2AgBBBBAeIgMgATYCAEGjOyAAQeI7QfooQcEBIAJB4jtB/ihBwgEgAxAHCzcBAX8gASAAKAIEIgNBAXVqIQEgACgCACEAIAEgAiADQQFxBH8gASgCACAAaigCAAUgAAsRBQALOQEBfyABIAAoAgQiBEEBdWohASAAKAIAIQAgASACIAMgBEEBcQR/IAEoAgAgAGooAgAFIAALEQMACwkAIAEgABEAAAsHACAAEQ4ACzUBAX8gASAAKAIEIgJBAXVqIQEgACgCACEAIAEgAkEBcQR/IAEoAgAgAGooAgAFIAALEQAACzABAX8jAEEQayICJAAgAiABNgIIIAJBCGogABECACEAIAIoAggQBiACQRBqJAAgAAsMACABIAAoAgARAAALCQAgAEEBOgAEC9coAQJ/QaA7QaE7QaI7QQBBjCZBB0GPJkEAQY8mQQBB2RZBkSZBCBAFQQgQHiIAQoiAgIAQNwMAQaA7QZcbQQZBoCZBuCZBCSAAQQEQAEGkO0GlO0GmO0GgO0GMJkEKQYwmQQtBjCZBDEG4EUGRJkENEAVBBBAeIgBBDjYCAEGkO0HoFEECQcAmQcgmQQ8gAEEAEABBoDtBowxBAkHMJkHUJkEQQREQA0GgO0GAHEEDQaQnQbAnQRJBExADQbg7Qbk7Qbo7QQBBjCZBFEGPJkEAQY8mQQBB6RZBkSZBFRAFQQgQHiIAQoiAgIAQNwMAQbg7QegcQQJBuCdByCZBFiAAQQEQAEG7O0G8O0G9O0G4O0GMJkEXQYwmQRhBjCZBGUHPEUGRJkEaEAVBBBAeIgBBGzYCAEG7O0HoFEECQcAnQcgmQRwgAEEAEABBuDtBowxBAkHIJ0HUJkEdQR4QA0G4O0GAHEEDQaQnQbAnQRJBHxADQb47Qb87QcA7QQBBjCZBIEGPJkEAQY8mQQBB2hpBkSZBIRAFQb47QQFB+CdBjCZBIkEjEA9BvjtBkBtBAUH4J0GMJkEiQSMQA0G+O0HpCEECQfwnQcgmQSRBJRADQQgQHiIAQQA2AgQgAEEmNgIAQb47Qa0cQQRBkChBoChBJyAAQQAQAEEIEB4iAEEANgIEIABBKDYCAEG+O0GkEUEDQagoQbQoQSkgAEEAEABBCBAeIgBBADYCBCAAQSo2AgBBvjtByB1BA0G8KEHIKEErIABBABAAQQgQHiIAQQA2AgQgAEEsNgIAQb47QaYQQQNB0ChByChBLSAAQQAQAEEIEB4iAEEANgIEIABBLjYCAEG+O0HLHEEDQdwoQbAnQS8gAEEAEABBCBAeIgBBADYCBCAAQTA2AgBBvjtB0h1BAkHoKEHUJkExIABBABAAQQgQHiIAQQA2AgQgAEEyNgIAQb47QZcQQQJB8ChB1CZBMyAAQQAQAEHBO0GECkH4KEE0QZEmQTUQCkHiD0EAEEhB6g5BCBBIQYITQRAQSEHxFUEYEEhBgxdBIBBIQfAOQSgQSEHBOxAJQaM7Qf8aQfgoQTZBkSZBNxAKQYMXQQAQkwFB8A5BCBCTAUGjOxAJQcI7QYobQfgoQThBkSZBORAKQQQQHiIAQQg2AgBBBBAeIgFBCDYCAEHCO0GEG0HiO0H6KEE6IABB4jtB/ihBOyABEAdBBBAeIgBBADYCAEEEEB4iAUEANgIAQcI7QeUOQds7QdQmQTwgAEHbO0HIKEE9IAEQB0HCOxAJQcM7QcQ7QcU7QQBBjCZBPkGPJkEAQY8mQQBB+xtBkSZBPxAFQcM7QQFBhClBjCZBwABBwQAQD0HDO0HXDkEBQYQpQYwmQcAAQcEAEANBwztB0BpBAkGIKUHUJkHCAEHDABADQcM7QekIQQJBkClByCZBxABBxQAQA0EIEB4iAEEANgIEIABBxgA2AgBBwztB9w9BAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABByAA2AgBBwztB6htBA0GYKUHIKEHJACAAQQAQAEEIEB4iAEEANgIEIABBygA2AgBBwztBnxtBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABBzAA2AgBBwztB0BRBBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABBzgA2AgBBwztBiA1BBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABBzwA2AgBBwztB3RNBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB0AA2AgBBwztB+QtBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB0QA2AgBBwztBuBBBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB0gA2AgBBwztB5RpBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB0wA2AgBBwztB/BRBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB1AA2AgBBwztBlRNBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB1QA2AgBBwztBtQpBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB1gA2AgBBwztBuBVBBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB1wA2AgBBwztBmw1BBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB2AA2AgBBwztB7RNBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB2QA2AgBBwztBxAlBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB2gA2AgBBwztB8QhBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB2wA2AgBBwztBhwlBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB3QA2AgBBwztB1BBBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB3gA2AgBBwztB5gxBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB3wA2AgBBwztBzBNBAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABB4AA2AgBBwztBrAlBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB4QA2AgBBwztBnxZBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB4gA2AgBBwztBoRdBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB4wA2AgBBwztBvw1BA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB5AA2AgBBwztB+xNBAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABB5QA2AgBBwztBkQ9BA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB5gA2AgBBwztBwQxBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB5wA2AgBBwztBvhNBAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABB6AA2AgBBwztBsxdBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB6QA2AgBBwztBzw1BA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB6gA2AgBBwztBpQ9BA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB6wA2AgBBwztB0gxBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB7AA2AgBBwztBiRdBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB7QA2AgBBwztBrA1BA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB7gA2AgBBwztB9w5BA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB7wA2AgBBwztBrQxBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB8AA2AgBBwztB/RhBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB8QA2AgBBwztBshRBA0HIKUH+KEHcACAAQQAQAEEIEB4iAEEANgIEIABB8gA2AgBBwztBlBJBBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB8wA2AgBBwztBzhlBBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB9AA2AgBBwztB4g1BBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB9QA2AgBBwztBrRNBBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB9gA2AgBBwztB+gxBBEGwKUHAKUHNACAAQQAQAEEIEB4iAEEANgIEIABB9wA2AgBBwztBnhVBA0GkKUHIKEHLACAAQQAQAEEIEB4iAEEANgIEIABB+AA2AgBBwztBrxtBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABB+gA2AgBBwztB3BRBA0HcKUGwJ0H7ACAAQQAQAEEIEB4iAEEANgIEIABB/AA2AgBBwztBiQxBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABB/QA2AgBBwztBxhBBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABB/gA2AgBBwztB8hpBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABB/wA2AgBBwztBjRVBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABBgAE2AgBBwztBoRNBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABBgQE2AgBBwztBxwpBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABBggE2AgBBwztBwhVBA0HcKUGwJ0H7ACAAQQAQAEEIEB4iAEEANgIEIABBgwE2AgBBwztB4RBBAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBhQE2AgBBwztBuAlBAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBhwE2AgBBwztBrRZBAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBiAE2AgBBwztBqhdBAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBiQE2AgBBwztBmw9BAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBigE2AgBBwztBvxdBAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBiwE2AgBBwztBsg9BAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBjAE2AgBBwztBlRdBAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBjQE2AgBBwztBhA9BAkHoKUHUJkGEASAAQQAQAEEIEB4iAEEANgIEIABBjgE2AgBBwztBihlBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABBjwE2AgBBwztBwRRBAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBkAE2AgBBwztBnhJBA0H4KUGEKkGRASAAQQAQAEEIEB4iAEEANgIEIABBkgE2AgBBwztB0AlBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABBkwE2AgBBwztB/AhBAkHUKUHUJkH5ACAAQQAQAEEIEB4iAEEANgIEIABBlAE2AgBBwztB2RlBA0HcKUGwJ0H7ACAAQQAQAEEIEB4iAEEANgIEIABBlQE2AgBBwztBtBNBA0GMKkGYKkGWASAAQQAQAEEIEB4iAEEANgIEIABBlwE2AgBBwztBhxxBBEGgKkGgKEGYASAAQQAQAEEIEB4iAEEANgIEIABBmQE2AgBBwztBnBxBA0GwKkHIKEGaASAAQQAQAEEIEB4iAEEANgIEIABBmwE2AgBBwztBmgpBAkG8KkHUJkGcASAAQQAQAEEIEB4iAEEANgIEIABBnQE2AgBBwztBmQxBAkHEKkHUJkGeASAAQQAQAEEIEB4iAEEANgIEIABBnwE2AgBBwztBkxxBA0HMKkGwJ0GgASAAQQAQAEEIEB4iAEEANgIEIABBoQE2AgBBwztBuxZBA0HYKkHIKEGiASAAQQAQAEEIEB4iAEEANgIEIABBowE2AgBBwztBvxtBAkHkKkHUJkGkASAAQQAQAEEIEB4iAEEANgIEIABBpQE2AgBBwztB0xtBA0HYKkHIKEGiASAAQQAQAEEIEB4iAEEANgIEIABBpgE2AgBBwztBqB1BA0HsKkHIKEGnASAAQQAQAEEIEB4iAEEANgIEIABBqAE2AgBBwztBph1BAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABBqQE2AgBBwztBuR1BA0H4KkHIKEGqASAAQQAQAEEIEB4iAEEANgIEIABBqwE2AgBBwztBtx1BAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABBrAE2AgBBwztB3whBAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABBrQE2AgBBwztB1whBAkGEK0HUJkGuASAAQQAQAEEIEB4iAEEANgIEIABBrwE2AgBBwztB3hVBAkGQKUHIJkHHACAAQQAQAEEIEB4iAEEANgIEIABBsAE2AgBBwztB3AlBAkGEK0HUJkGuASAAQQAQAEEIEB4iAEEANgIEIABBsQE2AgBBwztB6QlBBUGQK0GkK0GyASAAQQAQAEEIEB4iAEEANgIEIABBswE2AgBBwztB5w9BAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBtAE2AgBBwztB0Q9BAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBtQE2AgBBwztBhhNBAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBtgE2AgBBwztB+BVBAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBtwE2AgBBwztByxdBAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBuAE2AgBBwztBvw9BAkHwKUH6KEGGASAAQQAQAEEIEB4iAEEANgIEIABBuQE2AgBBwztB+QlBAkGsK0HUJkG6ASAAQQAQAEEIEB4iAEEANgIEIABBuwE2AgBBwztBzBVBA0H4KUGEKkGRASAAQQAQAEEIEB4iAEEANgIEIABBvAE2AgBBwztBqBJBA0H4KUGEKkGRASAAQQAQAEEIEB4iAEEANgIEIABBvQE2AgBBwztB5BlBA0H4KUGEKkGRASAAQQAQAEEIEB4iAEEANgIEIABBvgE2AgBBwztBqxVBAkHUKUHUJkH5ACAAQQAQAAtZAQF/IAAgACgCSCIBQQFrIAFyNgJIIAAoAgAiAUEIcQRAIAAgAUEgcjYCAEF/DwsgAEIANwIEIAAgACgCLCIBNgIcIAAgATYCFCAAIAEgACgCMGo2AhBBAAtHAAJAIAFBA00EfyAAIAFBAnRqQQRqBSABQQRrIgEgACgCGCIAKAIEIAAoAgAiAGtBAnVPDQEgACABQQJ0agsoAgAPCxACAAs4AQF/IAFBAEgEQBACAAsgAUEBa0EFdkEBaiIBQQJ0EB4hAiAAIAE2AgggAEEANgIEIAAgAjYCAAvSBQEJfyAAIAEvAQA7AQAgACABKQIENwIEIAAgASkCDDcCDCAAIAEoAhQ2AhQCQAJAIAEoAhgiA0UNAEEYEB4iBUEANgIIIAVCADcCACADKAIEIgEgAygCACICRwRAIAEgAmsiAkEASA0CIAUgAhAeIgE2AgAgBSABIAJqNgIIIAMoAgAiAiADKAIEIgZHBEADQCABIAIoAgA2AgAgAUEEaiEBIAJBBGoiAiAGRw0ACwsgBSABNgIECyAFQgA3AgwgBUEANgIUIAMoAhAiAUUNACAFQQxqIAEQnwEgAygCDCEGIAUgBSgCECIEIAMoAhAiAkEfcWogAkFgcWoiATYCEAJAAkAgBEUEQCABQQFrIQMMAQsgAUEBayIDIARBAWtzQSBJDQELIAUoAgwgA0EFdkEAIAFBIU8bQQJ0akEANgIACyAFKAIMIARBA3ZB/P///wFxaiEBIARBH3EiA0UEQCACQQBMDQEgAkEgbSEDIAJBH2pBP08EQCABIAYgA0ECdBAzGgsgAiADQQV0ayICQQBMDQEgASADQQJ0IgNqIgEgASgCAEF/QSAgAmt2IgFBf3NxIAMgBmooAgAgAXFyNgIADAELIAJBAEwNAEF/IAN0IQhBICADayEEIAJBIE4EQCAIQX9zIQkgASgCACEHA0AgASAHIAlxIAYoAgAiByADdHI2AgAgASABKAIEIAhxIAcgBHZyIgc2AgQgBkEEaiEGIAFBBGohASACQT9LIQogAkEgayECIAoNAAsgAkEATA0BCyABIAEoAgBBfyAEIAQgAiACIARKGyIEa3YgCHFBf3NxIAYoAgBBf0EgIAJrdnEiBiADdHI2AgAgAiAEayICQQBMDQAgASADIARqQQN2Qfz///8BcWoiASABKAIAQX9BICACa3ZBf3NxIAYgBHZyNgIACyAAKAIYIQEgACAFNgIYIAEEQCABEFsLDwsQAgALvQMBB38gAARAIwBBIGsiBiQAIAAoAgAiASgC5AMiAwRAIAMgARBvGiABQQA2AuQDCyABKALsAyICIAEoAugDIgNHBEBBASACIANrQQJ1IgIgAkEBTRshBEEAIQIDQCADIAJBAnRqKAIAQQA2AuQDIAJBAWoiAiAERw0ACwsgASADNgLsAwJAIAMgAUHwA2oiAigCAEYNACAGQQhqQQBBACACEEoiAigCBCABKALsAyABKALoAyIEayIFayIDIAQgBRAzIQUgASgC6AMhBCABIAU2AugDIAIgBDYCBCABKALsAyEFIAEgAigCCDYC7AMgAiAFNgIIIAEoAvADIQcgASACKAIMNgLwAyACIAQ2AgAgAiAHNgIMIAQgBUcEQCACIAUgBCAFa0EDakF8cWo2AggLIARFDQAgBBAnIAEoAugDIQMLIAMEQCABIAM2AuwDIAMQJwsgASgClAEhAyABQQA2ApQBIAMEQCADEFsLIAEQJyAAKAIIIQEgAEEANgIIIAEEQCABIAEoAgAoAgQRAAALIAAoAgQhASAAQQA2AgQgAQRAIAEgASgCACgCBBEAAAsgBkEgaiQAIAAQIwsLtQEBAX8jAEEQayICJAACfyABBEAgASgCACEBQYgEEB4gARBcIAENARogAkH3GTYCACACEHIQJAALQZQ7LQAARQRAQfg6QQM2AgBBiDtCgICAgICAgMA/NwIAQYA7QgA3AgBBlDtBAToAAEH8OkH8Oi0AAEH+AXE6AABB9DpBADYCAEGQO0EANgIAC0GIBBAeQfQ6EFwLIQEgAEIANwIEIAAgATYCACABIAA2AgQgAkEQaiQAIAALGwEBfyAABEAgACgCACIBBEAgARAjCyAAECMLC0kBAn9BBBAeIQFBIBAeIgBBADYCHCAAQoCAgICAgIDAPzcCFCAAQgA3AgwgAEEAOgAIIABBAzYCBCAAQQA2AgAgASAANgIAIAELIAAgAkEFR0EAIAIbRQRAQbgwIAMgBBBJDwsgAyAEEHALIgEBfiABIAKtIAOtQiCGhCAEIAARFQAiBUIgiKckASAFpwuoAQEFfyAAKAJUIgMoAgAhBSADKAIEIgQgACgCFCAAKAIcIgdrIgYgBCAGSRsiBgRAIAUgByAGECsaIAMgAygCACAGaiIFNgIAIAMgAygCBCAGayIENgIECyAEIAIgAiAESxsiBARAIAUgASAEECsaIAMgAygCACAEaiIFNgIAIAMgAygCBCAEazYCBAsgBUEAOgAAIAAgACgCLCIBNgIcIAAgATYCFCACCwQAQgALBABBAAuKBQIGfgJ/IAEgASgCAEEHakF4cSIBQRBqNgIAIAAhCSABKQMAIQMgASkDCCEGIwBBIGsiCCQAAkAgBkL///////////8AgyIEQoCAgICAgMCAPH0gBEKAgICAgIDA/8MAfVQEQCAGQgSGIANCPIiEIQQgA0L//////////w+DIgNCgYCAgICAgIAIWgRAIARCgYCAgICAgIDAAHwhAgwCCyAEQoCAgICAgICAQH0hAiADQoCAgICAgICACFINASACIARCAYN8IQIMAQsgA1AgBEKAgICAgIDA//8AVCAEQoCAgICAgMD//wBRG0UEQCAGQgSGIANCPIiEQv////////8Dg0KAgICAgICA/P8AhCECDAELQoCAgICAgID4/wAhAiAEQv///////7//wwBWDQBCACECIARCMIinIgBBkfcASQ0AIAMhAiAGQv///////z+DQoCAgICAgMAAhCIFIQcCQCAAQYH3AGsiAUHAAHEEQCACIAFBQGqthiEHQgAhAgwBCyABRQ0AIAcgAa0iBIYgAkHAACABa62IhCEHIAIgBIYhAgsgCCACNwMQIAggBzcDGAJAQYH4ACAAayIAQcAAcQRAIAUgAEFAaq2IIQNCACEFDAELIABFDQAgBUHAACAAa62GIAMgAK0iAoiEIQMgBSACiCEFCyAIIAM3AwAgCCAF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ASAAKAIAIQAgASACQQFxBH8gASgCACAAaigCAAUgAAsRCwALYQECfyMAQRBrIgIkACABIAAoAgQiA0EBdWohASAAKAIAIQAgAiABIANBAXEEfyABKAIAIABqKAIABSAACxEBAEEQEB4iACACKQMINwMIIAAgAikDADcDACACQRBqJAAgAAtjAQJ/IwBBEGsiAyQAIAEgACgCBCIEQQF1aiEBIAAoAgAhACADIAEgAiAEQQFxBH8gASgCACAAaigCAAUgAAsRAwBBEBAeIgAgAykDCDcDCCAAIAMpAwA3AwAgA0EQaiQAIAALNwEBfyABIAAoAgQiA0EBdWohASAAKAIAIQAgASACIANBAXEEfyABKAIAIABqKAIABSAACxEEAAs5AQF/IAEgACgCBCIEQQF1aiEBIAAoAgAhACABIAIgAyAEQQFxBH8gASgCACAAaigCAAUgAAsRCAALCQAgASAAEQIACwUAQcM7Cw8AIAEgACgCAGogAjYCAAsNACABIAAoAgBqKAIACxgBAX9BEBAeIgBCADcDCCAAQQA2AgAgAAsYAQF/QRAQHiIAQgA3AwAgAEIANwMIIAALDABBMBAeQQBBMBAqCzcBAX8gASAAKAIEIgNBAXVqIQEgACgCACEAIAEgAiADQQFxBH8gASgCACAAaigCAAUgAAsRHgALBQBBvjsLIQAgACABKAIAIAEgASwAC0EASBtBuzsgAigCABAQNgIACyoBAX9BDBAeIgFBADoABCABIAAoAgA2AgggAEEANgIAIAFB2Cc2AgAgAQsFAEG7OwsFAEG4OwshACAAIAEoAgAgASABLAALQQBIG0GkOyACKAIAEBA2AgAL2AEBBH8jAEEgayIDJAAgASgCACIEQfD///8HSQRAAkACQCAEQQtPBEAgBEEPckEBaiIFEB4hBiADIAVBgICAgHhyNgIQIAMgBjYCCCADIAQ2AgwgBCAGaiEFDAELIAMgBDoAEyADQQhqIgYgBGohBSAERQ0BCyAGIAFBBGogBBArGgsgBUEAOgAAIAMgAjYCACADQRhqIANBCGogAyAAEQMAIAMoAhgQHSADKAIYIgAQBiADKAIAEAYgAywAE0EASARAIAMoAggQIwsgA0EgaiQAIAAPCxACAAsqAQF/QQwQHiIBQQA6AAQgASAAKAIANgIIIABBADYCACABQeAmNgIA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AkEIaiAIIAYQHyACIAcgAC8AABAfQQEhAyACKgIIIgogAioCACILXAR/IAogClsNAyALIAtcBSADC0UNAiACLQAMIAItAARHDQILIABBAmohAEEBIQMgBCEGQQEhBCAGRQ0ACyABLwB6IgBBB3FFBEAgBS0AekEHcUUNAgsgCCAAECAiCiAHIAUvAHoQICILWw0BIAogClsNACALIAtcDQELIAFBFGogBUEUakHoABArGiABQfwAaiAFQfwAahCgAQNAIAEtAAAiAEEEcQ0BIAEgAEEEcjoAACABKAIQIgAEQCABIAARAAALIAFBgICA/gc2ApwBIAEoAuQDIgENAAsLIAJBEGokAAvGAwEEfyMAQaAEayICJAAgACgCBCEBIABBADYCBCABBEAgASABKAIAKAIEEQAACyAAKAIIIQEgAEEANgIIIAEEQCABIAEoAgAoAgQRAAALAkAgACgCACIAKALoAyAAKALsA0YEQCAAKALkAw0BIAAgAkEYaiAAKAL0AxBcIgEpAgA3AgAgACABKAIQNgIQIAAgASkCCDcCCCAAQRRqIAFBFGpB6AAQKxogACABKQKMATcCjAEgACABKQKEATcChAEgACABKQJ8NwJ8IAEoApQBIQQgAUEANgKUASAAKAKUASEDIAAgBDYClAEgAwRAIAMQWwsgAEGYAWogAUGYAWpB0AIQKxogACgC6AMiAwRAIAAgAzYC7AMgAxAjCyAAIAEoAugDNgLoAyAAIAEoAuwDNgLsAyAAIAEoAvADNgLwAyABQQA2AvADIAFCADcC6AMgACABKQL8AzcC/AMgACABKQL0AzcC9AMgACABKAKEBDYChAQgASgClAEhACABQQA2ApQBIAAEQCAAEFsLIAJBoARqJAAPCyACQfAcNgIQIABBBUHYJSACQRBqECwQJAALIAJB5hE2AgAgAEEFQdglIAIQLBAkAAsLAEEMEB4gABCiAQsLAEEMEB5BABCiAQsNACAAKAIALQAIQQFxCwoAIAAoAgAoAhQLGQAgAUH/AXEEQBACAAsgACgCACgCEEEBcQsYACAAKAIAIgAgAC0ACEH+AXEgAXI6AAgLJgAgASAAKAIAIgAoAhRHBEAgACABNgIUIAAgACgCDEEBajYCDAsLkgEBAn8jAEEQayICJAAgACgCACEAIAFDAAAAAGAEQCABIAAqAhhcBEAgACABOAIYIAAgACgCDEEBajYCDAsgAkEQaiQADwsgAkGIFDYCACMAQRBrIgMkACADIAI2AgwCQCAARQRAQbgwQdglIAIQSRoMAQsgAEEAQQVB2CUgAiAAKAIEEQ0AGgsgA0EQaiQAECQACz8AIAFB/wFxRQRAIAIgACgCACIAKAIQIgFBAXFHBEAgACABQX5xIAJyNgIQIAAgACgCDEEBajYCDAsPCxACAAsL4CYjAEGACAuBHk9ubHkgbGVhZiBub2RlcyB3aXRoIGN1c3RvbSBtZWFzdXJlIGZ1bmN0aW9ucyBzaG91bGQgbWFudWFsbHkgbWFyayB0aGVtc2VsdmVzIGFzIGRpcnR5AGlzRGlydHkAbWFya0RpcnR5AGRlc3Ryb3kAc2V0RGlzcGxheQBnZXREaXNwbGF5AHNldEZsZXgALSsgICAwWDB4AC0wWCswWCAwWC0weCsweCAweABzZXRGbGV4R3JvdwBnZXRGbGV4R3JvdwBzZXRPdmVyZmxvdwBnZXRPdmVyZmxvdwBoYXNOZXdMYXlvdXQAY2FsY3VsYXRlTGF5b3V0AGdldENvbXB1dGVkTGF5b3V0AHVuc2lnbmVkIHNob3J0AGdldENoaWxkQ291bnQAdW5zaWduZWQgaW50AHNldEp1c3RpZnlDb250ZW50AGdldEp1c3RpZnlDb250ZW50AGF2YWlsYWJsZUhlaWdodCBpcyBpbmRlZmluaXRlIHNvIGhlaWdodFNpemluZ01vZGUgbXVzdCBiZSBTaXppbmdNb2RlOjpNYXhDb250ZW50AGF2YWlsYWJsZVdpZHRoIGlzIGluZGVmaW5pdGUgc28gd2lkdGhTaXppbmdNb2RlIG11c3QgYmUgU2l6aW5nTW9kZTo6TWF4Q29udGVudABzZXRBbGlnbkNvbnRlbnQAZ2V0QWxpZ25Db250ZW50AGdldFBhcmVudABpbXBsZW1lbnQAc2V0TWF4SGVpZ2h0UGVyY2VudABzZXRIZWlnaHRQZXJjZW50AHNldE1pbkhlaWdodFBlcmNlbnQAc2V0RmxleEJhc2lzUGVyY2VudABzZXRHYXBQZXJjZW50AHNldFBvc2l0aW9uUGVyY2VudABzZXRNYXJnaW5QZXJjZW50AHNldE1heFdpZHRoUGVyY2VudABzZXRXaWR0aFBlcmNlbnQAc2V0TWluV2lkdGhQZXJjZW50AHNldFBhZGRpbmdQZXJjZW50AGhhbmRsZS50eXBlKCkgPT0gU3R5bGVWYWx1ZUhhbmRsZTo6VHlwZTo6UG9pbnQgfHwgaGFuZGxlLnR5cGUoKSA9PSBTdHlsZVZhbHVlSGFuZGxlOjpUeXBlOjpQZXJjZW50AGNyZWF0ZURlZmF1bHQAdW5pdAByaWdodABoZWlnaHQAc2V0TWF4SGVpZ2h0AGdldE1heEhlaWdodABzZXRIZWlnaHQAZ2V0SGVpZ2h0AHNldE1pbkhlaWdodABnZXRNaW5IZWlnaHQAZ2V0Q29tcHV0ZWRIZWlnaHQAZ2V0Q29tcHV0ZWRSaWdodABsZWZ0AGdldENvbXB1dGVkTGVmdAByZXNldABfX2Rlc3RydWN0AGZsb2F0AHVpbnQ2NF90AHVzZVdlYkRlZmF1bHRzAHNldFVzZVdlYkRlZmF1bHRzAHNldEFsaWduSXRlbXMAZ2V0QWxpZ25JdGVtcwBzZXRGbGV4QmFzaXMAZ2V0RmxleEJhc2lzAENhbm5vdCBnZXQgbGF5b3V0IHByb3BlcnRpZXMgb2YgbXVsdGktZWRnZSBzaG9ydGhhbmRzAHNldFBvaW50U2NhbGVGYWN0b3IATWVhc3VyZUNhbGxiYWNrV3JhcHBlcgBEaXJ0aWVkQ2FsbGJhY2tXcmFwcGVyAENhbm5vdCByZXNldCBhIG5vZGUgc3RpbGwgYXR0YWNoZWQgdG8gYSBvd25lcgBzZXRCb3JkZXIAZ2V0Qm9yZGVyAGdldENvbXB1dGVkQm9yZGVyAGdldE51bWJlcgBoYW5kbGUudHlwZSgpID09IFN0eWxlVmFsdWVIYW5kbGU6OlR5cGU6Ok51bWJlcgB1bnNpZ25lZCBjaGFyAHRvcABnZXRDb21wdXRlZFRvcABzZXRGbGV4V3JhcABnZXRGbGV4V3JhcABzZXRHYXAAZ2V0R2FwACVwAHNldEhlaWdodEF1dG8Ac2V0RmxleEJhc2lzQXV0bwBzZXRQb3NpdGlvbkF1dG8Ac2V0TWFyZ2luQXV0bwBzZXRXaWR0aEF1dG8AU2NhbGUgZmFjdG9yIHNob3VsZCBub3QgYmUgbGVzcyB0aGFuIHplcm8Ac2V0QXNwZWN0UmF0aW8AZ2V0QXNwZWN0UmF0aW8Ac2V0UG9zaXRpb24AZ2V0UG9zaXRpb24Abm90aWZ5T25EZXN0cnVjdGlvbgBzZXRGbGV4RGlyZWN0aW9uAGdldEZsZXhEaXJlY3Rpb24Ac2V0RGlyZWN0aW9uAGdldERpcmVjdGlvbgBzZXRNYXJnaW4AZ2V0TWFyZ2luAGdldENvbXB1dGVkTWFyZ2luAG1hcmtMYXlvdXRTZWVuAG5hbgBib3R0b20AZ2V0Q29tcHV0ZWRCb3R0b20AYm9vbABlbXNjcmlwdGVuOjp2YWwAc2V0RmxleFNocmluawBnZXRGbGV4U2hyaW5rAHNldEFsd2F5c0Zvcm1zQ29udGFpbmluZ0Jsb2NrAE1lYXN1cmVDYWxsYmFjawBEaXJ0aWVkQ2FsbGJhY2sAZ2V0TGVuZ3RoAHdpZHRoAHNldE1heFdpZHRoAGdldE1heFdpZHRoAHNldFdpZHRoAGdldFdpZHRoAHNldE1pbldpZHRoAGdldE1pbldpZHRoAGdldENvbXB1dGVkV2lkdGgAcHVzaAAvaG9tZS9ydW5uZXIvd29yay95b2dhL3lvZ2EvamF2YXNjcmlwdC8uLi95b2dhL3N0eWxlL1NtYWxsVmFsdWVCdWZmZXIuaAAvaG9tZS9ydW5uZXIvd29yay95b2dhL3lvZ2EvamF2YXNjcmlwdC8uLi95b2dhL3N0eWxlL1N0eWxlVmFsdWVQb29sLmgAdW5zaWduZWQgbG9uZwBzZXRCb3hTaXppbmcAZ2V0Qm94U2l6aW5nAHN0ZDo6d3N0cmluZwBzdGQ6OnN0cmluZwBzdGQ6OnUxNnN0cmluZwBzdGQ6OnUzMnN0cmluZwBzZXRQYWRkaW5nAGdldFBhZGRpbmcAZ2V0Q29tcHV0ZWRQYWRkaW5nAFRyaWVkIHRvIGNvbnN0cnVjdCBZR05vZGUgd2l0aCBudWxsIGNvbmZpZwBBdHRlbXB0aW5nIHRvIGNvbnN0cnVjdCBOb2RlIHdpdGggbnVsbCBjb25maWcAY3JlYXRlV2l0aENvbmZpZwBpbmYAc2V0QWxpZ25TZWxmAGdldEFsaWduU2VsZgBTaXplAHZhbHVlAFZhbHVlAGNyZWF0ZQBtZWFzdXJlAHNldFBvc2l0aW9uVHlwZQBnZXRQb3NpdGlvblR5cGUAaXNSZWZlcmVuY2VCYXNlbGluZQBzZXRJc1JlZmVyZW5jZUJhc2VsaW5lAGNvcHlTdHlsZQBkb3VibGUATm9kZQBleHRlbmQAaW5zZXJ0Q2hpbGQAZ2V0Q2hpbGQAcmVtb3ZlQ2hpbGQAdm9pZABzZXRFeHBlcmltZW50YWxGZWF0dXJlRW5hYmxlZABpc0V4cGVyaW1lbnRhbEZlYXR1cmVFbmFibGVkAGRpcnRpZWQAQ2Fubm90IHJlc2V0IGEgbm9kZSB3aGljaCBzdGlsbCBoYXMgY2hpbGRyZW4gYXR0YWNoZWQAdW5zZXRNZWFzdXJlRnVuYwB1bnNldERpcnRpZWRGdW5jAHNldEVycmF0YQBnZXRFcnJhdGEATWVhc3VyZSBmdW5jdGlvbiByZXR1cm5lZCBhbiBpbnZhbGlkIGRpbWVuc2lvbiB0byBZb2dhOiBbd2lkdGg9JWYsIGhlaWdodD0lZl0ARXhwZWN0IGN1c3RvbSBiYXNlbGluZSBmdW5jdGlvbiB0byBub3QgcmV0dXJuIE5hTgBOQU4ASU5GAGVtc2NyaXB0ZW46Om1lbW9yeV92aWV3PHNob3J0PgBlbXNjcmlwdGVuOjptZW1vcnlfdmlldzx1bnNpZ25lZCBzaG9ydD4AZW1zY3JpcHRlbjo6bWVtb3J5X3ZpZXc8aW50PgBlbXNjcmlwdGVuOjptZW1vcnlfdmlldzx1bnNpZ25lZCBpbnQ+AGVtc2NyaXB0ZW46Om1lbW9yeV92aWV3PGZsb2F0PgBlbXNjcmlwdGVuOjptZW1vcnlfdmlldzx1aW50OF90PgBlbXNjcmlwdGVuOjptZW1vcnlfdmlldzxpbnQ4X3Q+AGVtc2NyaXB0ZW46Om1lbW9yeV92aWV3PHVpbnQxNl90PgBlbXNjcmlwdGVuOjptZW1vcnlfdmlldzxpbnQxNl90PgBlbXNjcmlwdGVuOjptZW1vcnlfdmlldzx1aW50MzJfdD4AZW1zY3JpcHRlbjo6bWVtb3J5X3ZpZXc8aW50MzJfdD4AZW1zY3JpcHRlbjo6bWVtb3J5X3ZpZXc8Y2hhcj4AZW1zY3JpcHRlbjo6bWVtb3J5X3ZpZXc8dW5zaWduZWQgY2hhcj4Ac3RkOjpiYXNpY19zdHJpbmc8dW5zaWduZWQgY2hhcj4AZW1zY3JpcHRlbjo6bWVtb3J5X3ZpZXc8c2lnbmVk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";
    if (!ua(H)) {
      var va = H;
      H = h.locateFile ? h.locateFile(va, q) : q + va;
    }
    function wa() {
      var a = H;
      try {
        if (a == H && w)
          return new Uint8Array(w);
        if (ua(a))
          try {
            var b = xa(a.slice(37)), c = new Uint8Array(b.length);
            for (a = 0;a < b.length; ++a)
              c[a] = b.charCodeAt(a);
            var d = c;
          } catch (f) {
            throw Error("Converting base64 string to bytes failed.");
          }
        else
          d = undefined;
        var e = d;
        if (e)
          return e;
        throw "both async and sync fetching of the wasm failed";
      } catch (f) {
        x(f);
      }
    }
    function ya() {
      return w || typeof fetch != "function" ? Promise.resolve().then(function() {
        return wa();
      }) : fetch(H, { credentials: "same-origin" }).then(function(a) {
        if (!a.ok)
          throw "failed to load wasm binary file at '" + H + "'";
        return a.arrayBuffer();
      }).catch(function() {
        return wa();
      });
    }
    function za(a) {
      for (;0 < a.length; )
        a.shift()(h);
    }
    function Aa(a) {
      if (a === undefined)
        return "_unknown";
      a = a.replace(/[^a-zA-Z0-9_]/g, "$");
      var b = a.charCodeAt(0);
      return 48 <= b && 57 >= b ? "_" + a : a;
    }
    function Ba(a, b) {
      a = Aa(a);
      return function() {
        return b.apply(this, arguments);
      };
    }
    var J = [{}, { value: undefined }, { value: null }, { value: true }, { value: false }], Ca = [];
    function Da(a) {
      var b = Error, c = Ba(a, function(d) {
        this.name = a;
        this.message = d;
        d = Error(d).stack;
        d !== undefined && (this.stack = this.toString() + `
` + d.replace(/^Error(:[^\n]*)?\n/, ""));
      });
      c.prototype = Object.create(b.prototype);
      c.prototype.constructor = c;
      c.prototype.toString = function() {
        return this.message === undefined ? this.name : this.name + ": " + this.message;
      };
      return c;
    }
    var K = undefined;
    function L(a) {
      throw new K(a);
    }
    var M = (a) => {
      a || L("Cannot use deleted val. handle = " + a);
      return J[a].value;
    }, Ea = (a) => {
      switch (a) {
        case undefined:
          return 1;
        case null:
          return 2;
        case true:
          return 3;
        case false:
          return 4;
        default:
          var b = Ca.length ? Ca.pop() : J.length;
          J[b] = { ga: 1, value: a };
          return b;
      }
    }, Fa = undefined, Ga = undefined;
    function N(a) {
      for (var b = "";A[a]; )
        b += Ga[A[a++]];
      return b;
    }
    var O = [];
    function Ha() {
      for (;O.length; ) {
        var a = O.pop();
        a.M.$ = false;
        a["delete"]();
      }
    }
    var P = undefined, Q = {};
    function Ia(a, b) {
      for (b === undefined && L("ptr should not be undefined");a.R; )
        b = a.ba(b), a = a.R;
      return b;
    }
    var R = {};
    function Ja(a) {
      a = Ka(a);
      var b = N(a);
      S(a);
      return b;
    }
    function La(a, b) {
      var c = R[a];
      c === undefined && L(b + " has unknown type " + Ja(a));
      return c;
    }
    function Ma() {}
    var Na = false;
    function Oa(a) {
      --a.count.value;
      a.count.value === 0 && (a.T ? a.U.W(a.T) : a.P.N.W(a.O));
    }
    function Pa(a, b, c) {
      if (b === c)
        return a;
      if (c.R === undefined)
        return null;
      a = Pa(a, b, c.R);
      return a === null ? null : c.na(a);
    }
    var Qa = {};
    function Ra(a, b) {
      b = Ia(a, b);
      return Q[b];
    }
    var Sa = undefined;
    function Ta(a) {
      throw new Sa(a);
    }
    function Ua(a, b) {
      b.P && b.O || Ta("makeClassHandle requires ptr and ptrType");
      !!b.U !== !!b.T && Ta("Both smartPtrType and smartPtr must be specified");
      b.count = { value: 1 };
      return T(Object.create(a, { M: { value: b } }));
    }
    function T(a) {
      if (typeof FinalizationRegistry === "undefined")
        return T = (b) => b, a;
      Na = new FinalizationRegistry((b) => {
        Oa(b.M);
      });
      T = (b) => {
        var c = b.M;
        c.T && Na.register(b, { M: c }, b);
        return b;
      };
      Ma = (b) => {
        Na.unregister(b);
      };
      return T(a);
    }
    var Va = {};
    function Wa(a) {
      for (;a.length; ) {
        var b = a.pop();
        a.pop()(b);
      }
    }
    function Xa(a) {
      return this.fromWireType(D[a >> 2]);
    }
    var U = {}, Ya = {};
    function V(a, b, c) {
      function d(k) {
        k = c(k);
        k.length !== a.length && Ta("Mismatched type converter count");
        for (var m = 0;m < a.length; ++m)
          W(a[m], k[m]);
      }
      a.forEach(function(k) {
        Ya[k] = b;
      });
      var e = Array(b.length), f = [], g = 0;
      b.forEach((k, m) => {
        R.hasOwnProperty(k) ? e[m] = R[k] : (f.push(k), U.hasOwnProperty(k) || (U[k] = []), U[k].push(() => {
          e[m] = R[k];
          ++g;
          g === f.length && d(e);
        }));
      });
      f.length === 0 && d(e);
    }
    function Za(a) {
      switch (a) {
        case 1:
          return 0;
        case 2:
          return 1;
        case 4:
          return 2;
        case 8:
          return 3;
        default:
          throw new TypeError("Unknown type size: " + a);
      }
    }
    function W(a, b, c = {}) {
      if (!("argPackAdvance" in b))
        throw new TypeError("registerType registeredInstance requires argPackAdvance");
      var d = b.name;
      a || L('type "' + d + '" must have a positive integer typeid pointer');
      if (R.hasOwnProperty(a)) {
        if (c.ua)
          return;
        L("Cannot register type '" + d + "' twice");
      }
      R[a] = b;
      delete Ya[a];
      U.hasOwnProperty(a) && (b = U[a], delete U[a], b.forEach((e) => e()));
    }
    function $a(a) {
      L(a.M.P.N.name + " instance already deleted");
    }
    function X() {}
    function ab(a, b, c) {
      if (a[b].S === undefined) {
        var d = a[b];
        a[b] = function() {
          a[b].S.hasOwnProperty(arguments.length) || L("Function '" + c + "' called with an invalid number of arguments (" + arguments.length + ") - expects one of (" + a[b].S + ")!");
          return a[b].S[arguments.length].apply(this, arguments);
        };
        a[b].S = [];
        a[b].S[d.Z] = d;
      }
    }
    function bb(a, b) {
      h.hasOwnProperty(a) ? (L("Cannot register public name '" + a + "' twice"), ab(h, a, a), h.hasOwnProperty(undefined) && L("Cannot register multiple overloads of a function with the same number of arguments (undefined)!"), h[a].S[undefined] = b) : h[a] = b;
    }
    function cb(a, b, c, d, e, f, g, k) {
      this.name = a;
      this.constructor = b;
      this.X = c;
      this.W = d;
      this.R = e;
      this.pa = f;
      this.ba = g;
      this.na = k;
      this.ja = [];
    }
    function db(a, b, c) {
      for (;b !== c; )
        b.ba || L("Expected null or instance of " + c.name + ", got an instance of " + b.name), a = b.ba(a), b = b.R;
      return a;
    }
    function eb(a, b) {
      if (b === null)
        return this.ea && L("null is not a valid " + this.name), 0;
      b.M || L('Cannot pass "' + fb(b) + '" as a ' + this.name);
      b.M.O || L("Cannot pass deleted object as a pointer of type " + this.name);
      return db(b.M.O, b.M.P.N, this.N);
    }
    function gb(a, b) {
      if (b === null) {
        this.ea && L("null is not a valid " + this.name);
        if (this.da) {
          var c = this.fa();
          a !== null && a.push(this.W, c);
          return c;
        }
        return 0;
      }
      b.M || L('Cannot pass "' + fb(b) + '" as a ' + this.name);
      b.M.O || L("Cannot pass deleted object as a pointer of type " + this.name);
      !this.ca && b.M.P.ca && L("Cannot convert argument of type " + (b.M.U ? b.M.U.name : b.M.P.name) + " to parameter type " + this.name);
      c = db(b.M.O, b.M.P.N, this.N);
      if (this.da)
        switch (b.M.T === undefined && L("Passing raw pointer to smart pointer is illegal"), this.Ba) {
          case 0:
            b.M.U === this ? c = b.M.T : L("Cannot convert argument of type " + (b.M.U ? b.M.U.name : b.M.P.name) + " to parameter type " + this.name);
            break;
          case 1:
            c = b.M.T;
            break;
          case 2:
            if (b.M.U === this)
              c = b.M.T;
            else {
              var d = b.clone();
              c = this.xa(c, Ea(function() {
                d["delete"]();
              }));
              a !== null && a.push(this.W, c);
            }
            break;
          default:
            L("Unsupporting sharing policy");
        }
      return c;
    }
    function hb(a, b) {
      if (b === null)
        return this.ea && L("null is not a valid " + this.name), 0;
      b.M || L('Cannot pass "' + fb(b) + '" as a ' + this.name);
      b.M.O || L("Cannot pass deleted object as a pointer of type " + this.name);
      b.M.P.ca && L("Cannot convert argument of type " + b.M.P.name + " to parameter type " + this.name);
      return db(b.M.O, b.M.P.N, this.N);
    }
    function Y(a, b, c, d) {
      this.name = a;
      this.N = b;
      this.ea = c;
      this.ca = d;
      this.da = false;
      this.W = this.xa = this.fa = this.ka = this.Ba = this.wa = undefined;
      b.R !== undefined ? this.toWireType = gb : (this.toWireType = d ? eb : hb, this.V = null);
    }
    function ib(a, b) {
      h.hasOwnProperty(a) || Ta("Replacing nonexistant public symbol");
      h[a] = b;
      h[a].Z = undefined;
    }
    function jb(a, b) {
      var c = [];
      return function() {
        c.length = 0;
        Object.assign(c, arguments);
        if (a.includes("j")) {
          var d = h["dynCall_" + a];
          d = c && c.length ? d.apply(null, [b].concat(c)) : d.call(null, b);
        } else
          d = oa.get(b).apply(null, c);
        return d;
      };
    }
    function Z(a, b) {
      a = N(a);
      var c = a.includes("j") ? jb(a, b) : oa.get(b);
      typeof c != "function" && L("unknown function pointer with signature " + a + ": " + b);
      return c;
    }
    var mb = undefined;
    function nb(a, b) {
      function c(f) {
        e[f] || R[f] || (Ya[f] ? Ya[f].forEach(c) : (d.push(f), e[f] = true));
      }
      var d = [], e = {};
      b.forEach(c);
      throw new mb(a + ": " + d.map(Ja).join([", "]));
    }
    function ob(a, b, c, d, e) {
      var f = b.length;
      2 > f && L("argTypes array size mismatch! Must at least get return value and 'this' types!");
      var g = b[1] !== null && c !== null, k = false;
      for (c = 1;c < b.length; ++c)
        if (b[c] !== null && b[c].V === undefined) {
          k = true;
          break;
        }
      var m = b[0].name !== "void", l = f - 2, n = Array(l), p = [], r = [];
      return function() {
        arguments.length !== l && L("function " + a + " called with " + arguments.length + " arguments, expected " + l + " args!");
        r.length = 0;
        p.length = g ? 2 : 1;
        p[0] = e;
        if (g) {
          var u = b[1].toWireType(r, this);
          p[1] = u;
        }
        for (var t = 0;t < l; ++t)
          n[t] = b[t + 2].toWireType(r, arguments[t]), p.push(n[t]);
        t = d.apply(null, p);
        if (k)
          Wa(r);
        else
          for (var y = g ? 1 : 2;y < b.length; y++) {
            var B = y === 1 ? u : n[y - 2];
            b[y].V !== null && b[y].V(B);
          }
        u = m ? b[0].fromWireType(t) : undefined;
        return u;
      };
    }
    function pb(a, b) {
      for (var c = [], d = 0;d < a; d++)
        c.push(E[b + 4 * d >> 2]);
      return c;
    }
    function qb(a) {
      4 < a && --J[a].ga === 0 && (J[a] = undefined, Ca.push(a));
    }
    function fb(a) {
      if (a === null)
        return "null";
      var b = typeof a;
      return b === "object" || b === "array" || b === "function" ? a.toString() : "" + a;
    }
    function rb(a, b) {
      switch (b) {
        case 2:
          return function(c) {
            return this.fromWireType(la[c >> 2]);
          };
        case 3:
          return function(c) {
            return this.fromWireType(ma[c >> 3]);
          };
        default:
          throw new TypeError("Unknown float type: " + a);
      }
    }
    function sb(a, b, c) {
      switch (b) {
        case 0:
          return c ? function(d) {
            return ja[d];
          } : function(d) {
            return A[d];
          };
        case 1:
          return c ? function(d) {
            return C[d >> 1];
          } : function(d) {
            return ka[d >> 1];
          };
        case 2:
          return c ? function(d) {
            return D[d >> 2];
          } : function(d) {
            return E[d >> 2];
          };
        default:
          throw new TypeError("Unknown integer type: " + a);
      }
    }
    function tb(a, b) {
      for (var c = "", d = 0;!(d >= b / 2); ++d) {
        var e = C[a + 2 * d >> 1];
        if (e == 0)
          break;
        c += String.fromCharCode(e);
      }
      return c;
    }
    function ub(a, b, c) {
      c === undefined && (c = 2147483647);
      if (2 > c)
        return 0;
      c -= 2;
      var d = b;
      c = c < 2 * a.length ? c / 2 : a.length;
      for (var e = 0;e < c; ++e)
        C[b >> 1] = a.charCodeAt(e), b += 2;
      C[b >> 1] = 0;
      return b - d;
    }
    function vb(a) {
      return 2 * a.length;
    }
    function wb(a, b) {
      for (var c = 0, d = "";!(c >= b / 4); ) {
        var e = D[a + 4 * c >> 2];
        if (e == 0)
          break;
        ++c;
        65536 <= e ? (e -= 65536, d += String.fromCharCode(55296 | e >> 10, 56320 | e & 1023)) : d += String.fromCharCode(e);
      }
      return d;
    }
    function xb(a, b, c) {
      c === undefined && (c = 2147483647);
      if (4 > c)
        return 0;
      var d = b;
      c = d + c - 4;
      for (var e = 0;e < a.length; ++e) {
        var f = a.charCodeAt(e);
        if (55296 <= f && 57343 >= f) {
          var g = a.charCodeAt(++e);
          f = 65536 + ((f & 1023) << 10) | g & 1023;
        }
        D[b >> 2] = f;
        b += 4;
        if (b + 4 > c)
          break;
      }
      D[b >> 2] = 0;
      return b - d;
    }
    function yb(a) {
      for (var b = 0, c = 0;c < a.length; ++c) {
        var d = a.charCodeAt(c);
        55296 <= d && 57343 >= d && ++c;
        b += 4;
      }
      return b;
    }
    var zb = {};
    function Ab(a) {
      var b = zb[a];
      return b === undefined ? N(a) : b;
    }
    var Bb = [];
    function Cb(a) {
      var b = Bb.length;
      Bb.push(a);
      return b;
    }
    function Db(a, b) {
      for (var c = Array(a), d = 0;d < a; ++d)
        c[d] = La(E[b + 4 * d >> 2], "parameter " + d);
      return c;
    }
    var Eb = [], Fb = [null, [], []];
    K = h.BindingError = Da("BindingError");
    h.count_emval_handles = function() {
      for (var a = 0, b = 5;b < J.length; ++b)
        J[b] !== undefined && ++a;
      return a;
    };
    h.get_first_emval = function() {
      for (var a = 5;a < J.length; ++a)
        if (J[a] !== undefined)
          return J[a];
      return null;
    };
    Fa = h.PureVirtualError = Da("PureVirtualError");
    for (var Gb = Array(256), Hb = 0;256 > Hb; ++Hb)
      Gb[Hb] = String.fromCharCode(Hb);
    Ga = Gb;
    h.getInheritedInstanceCount = function() {
      return Object.keys(Q).length;
    };
    h.getLiveInheritedInstances = function() {
      var a = [], b;
      for (b in Q)
        Q.hasOwnProperty(b) && a.push(Q[b]);
      return a;
    };
    h.flushPendingDeletes = Ha;
    h.setDelayFunction = function(a) {
      P = a;
      O.length && P && P(Ha);
    };
    Sa = h.InternalError = Da("InternalError");
    X.prototype.isAliasOf = function(a) {
      if (!(this instanceof X && a instanceof X))
        return false;
      var b = this.M.P.N, c = this.M.O, d = a.M.P.N;
      for (a = a.M.O;b.R; )
        c = b.ba(c), b = b.R;
      for (;d.R; )
        a = d.ba(a), d = d.R;
      return b === d && c === a;
    };
    X.prototype.clone = function() {
      this.M.O || $a(this);
      if (this.M.aa)
        return this.M.count.value += 1, this;
      var a = T, b = Object, c = b.create, d = Object.getPrototypeOf(this), e = this.M;
      a = a(c.call(b, d, { M: { value: { count: e.count, $: e.$, aa: e.aa, O: e.O, P: e.P, T: e.T, U: e.U } } }));
      a.M.count.value += 1;
      a.M.$ = false;
      return a;
    };
    X.prototype["delete"] = function() {
      this.M.O || $a(this);
      this.M.$ && !this.M.aa && L("Object already scheduled for deletion");
      Ma(this);
      Oa(this.M);
      this.M.aa || (this.M.T = undefined, this.M.O = undefined);
    };
    X.prototype.isDeleted = function() {
      return !this.M.O;
    };
    X.prototype.deleteLater = function() {
      this.M.O || $a(this);
      this.M.$ && !this.M.aa && L("Object already scheduled for deletion");
      O.push(this);
      O.length === 1 && P && P(Ha);
      this.M.$ = true;
      return this;
    };
    Y.prototype.qa = function(a) {
      this.ka && (a = this.ka(a));
      return a;
    };
    Y.prototype.ha = function(a) {
      this.W && this.W(a);
    };
    Y.prototype.argPackAdvance = 8;
    Y.prototype.readValueFromPointer = Xa;
    Y.prototype.deleteObject = function(a) {
      if (a !== null)
        a["delete"]();
    };
    Y.prototype.fromWireType = function(a) {
      function b() {
        return this.da ? Ua(this.N.X, { P: this.wa, O: c, U: this, T: a }) : Ua(this.N.X, { P: this, O: a });
      }
      var c = this.qa(a);
      if (!c)
        return this.ha(a), null;
      var d = Ra(this.N, c);
      if (d !== undefined) {
        if (d.M.count.value === 0)
          return d.M.O = c, d.M.T = a, d.clone();
        d = d.clone();
        this.ha(a);
        return d;
      }
      d = this.N.pa(c);
      d = Qa[d];
      if (!d)
        return b.call(this);
      d = this.ca ? d.la : d.pointerType;
      var e = Pa(c, this.N, d.N);
      return e === null ? b.call(this) : this.da ? Ua(d.N.X, { P: d, O: e, U: this, T: a }) : Ua(d.N.X, { P: d, O: e });
    };
    mb = h.UnboundTypeError = Da("UnboundTypeError");
    var xa = typeof atob == "function" ? atob : function(a) {
      var b = "", c = 0;
      a = a.replace(/[^A-Za-z0-9\+\/=]/g, "");
      do {
        var d = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=".indexOf(a.charAt(c++));
        var e = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=".indexOf(a.charAt(c++));
        var f = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=".indexOf(a.charAt(c++));
        var g = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=".indexOf(a.charAt(c++));
        d = d << 2 | e >> 4;
        e = (e & 15) << 4 | f >> 2;
        var k = (f & 3) << 6 | g;
        b += String.fromCharCode(d);
        f !== 64 && (b += String.fromCharCode(e));
        g !== 64 && (b += String.fromCharCode(k));
      } while (c < a.length);
      return b;
    }, Jb = {
      l: function(a, b, c, d) {
        x("Assertion failed: " + (a ? z(A, a) : "") + ", at: " + [b ? b ? z(A, b) : "" : "unknown filename", c, d ? d ? z(A, d) : "" : "unknown function"]);
      },
      q: function(a, b, c) {
        a = N(a);
        b = La(b, "wrapper");
        c = M(c);
        var d = [].slice, e = b.N, f = e.X, g = e.R.X, k = e.R.constructor;
        a = Ba(a, function() {
          e.R.ja.forEach(function(l) {
            if (this[l] === g[l])
              throw new Fa("Pure virtual function " + l + " must be implemented in JavaScript");
          }.bind(this));
          Object.defineProperty(this, "__parent", { value: f });
          this.__construct.apply(this, d.call(arguments));
        });
        f.__construct = function() {
          this === f && L("Pass correct 'this' to __construct");
          var l = k.implement.apply(undefined, [this].concat(d.call(arguments)));
          Ma(l);
          var n = l.M;
          l.notifyOnDestruction();
          n.aa = true;
          Object.defineProperties(this, { M: { value: n } });
          T(this);
          l = n.O;
          l = Ia(e, l);
          Q.hasOwnProperty(l) ? L("Tried to register registered instance: " + l) : Q[l] = this;
        };
        f.__destruct = function() {
          this === f && L("Pass correct 'this' to __destruct");
          Ma(this);
          var l = this.M.O;
          l = Ia(e, l);
          Q.hasOwnProperty(l) ? delete Q[l] : L("Tried to unregister unregistered instance: " + l);
        };
        a.prototype = Object.create(f);
        for (var m in c)
          a.prototype[m] = c[m];
        return Ea(a);
      },
      j: function(a) {
        var b = Va[a];
        delete Va[a];
        var { fa: c, W: d, ia: e } = b, f = e.map((g) => g.ta).concat(e.map((g) => g.za));
        V([a], f, (g) => {
          var k = {};
          e.forEach((m, l) => {
            var n = g[l], p = m.ra, r = m.sa, u = g[l + e.length], t = m.ya, y = m.Aa;
            k[m.oa] = { read: (B) => n.fromWireType(p(r, B)), write: (B, ba) => {
              var I = [];
              t(y, B, u.toWireType(I, ba));
              Wa(I);
            } };
          });
          return [{ name: b.name, fromWireType: function(m) {
            var l = {}, n;
            for (n in k)
              l[n] = k[n].read(m);
            d(m);
            return l;
          }, toWireType: function(m, l) {
            for (var n in k)
              if (!(n in l))
                throw new TypeError('Missing field:  "' + n + '"');
            var p = c();
            for (n in k)
              k[n].write(p, l[n]);
            m !== null && m.push(d, p);
            return p;
          }, argPackAdvance: 8, readValueFromPointer: Xa, V: d }];
        });
      },
      v: function() {},
      B: function(a, b, c, d, e) {
        var f = Za(c);
        b = N(b);
        W(a, {
          name: b,
          fromWireType: function(g) {
            return !!g;
          },
          toWireType: function(g, k) {
            return k ? d : e;
          },
          argPackAdvance: 8,
          readValueFromPointer: function(g) {
            if (c === 1)
              var k = ja;
            else if (c === 2)
              k = C;
            else if (c === 4)
              k = D;
            else
              throw new TypeError("Unknown boolean type size: " + b);
            return this.fromWireType(k[g >> f]);
          },
          V: null
        });
      },
      f: function(a, b, c, d, e, f, g, k, m, l, n, p, r) {
        n = N(n);
        f = Z(e, f);
        k && (k = Z(g, k));
        l && (l = Z(m, l));
        r = Z(p, r);
        var u = Aa(n);
        bb(u, function() {
          nb("Cannot construct " + n + " due to unbound types", [d]);
        });
        V([a, b, c], d ? [d] : [], function(t) {
          t = t[0];
          if (d) {
            var y = t.N;
            var B = y.X;
          } else
            B = X.prototype;
          t = Ba(u, function() {
            if (Object.getPrototypeOf(this) !== ba)
              throw new K("Use 'new' to construct " + n);
            if (I.Y === undefined)
              throw new K(n + " has no accessible constructor");
            var kb = I.Y[arguments.length];
            if (kb === undefined)
              throw new K("Tried to invoke ctor of " + n + " with invalid number of parameters (" + arguments.length + ") - expected (" + Object.keys(I.Y).toString() + ") parameters instead!");
            return kb.apply(this, arguments);
          });
          var ba = Object.create(B, { constructor: { value: t } });
          t.prototype = ba;
          var I = new cb(n, t, ba, r, y, f, k, l);
          y = new Y(n, I, true, false);
          B = new Y(n + "*", I, false, false);
          var lb = new Y(n + " const*", I, false, true);
          Qa[a] = {
            pointerType: B,
            la: lb
          };
          ib(u, t);
          return [y, B, lb];
        });
      },
      d: function(a, b, c, d, e, f, g) {
        var k = pb(c, d);
        b = N(b);
        f = Z(e, f);
        V([], [a], function(m) {
          function l() {
            nb("Cannot call " + n + " due to unbound types", k);
          }
          m = m[0];
          var n = m.name + "." + b;
          b.startsWith("@@") && (b = Symbol[b.substring(2)]);
          var p = m.N.constructor;
          p[b] === undefined ? (l.Z = c - 1, p[b] = l) : (ab(p, b, n), p[b].S[c - 1] = l);
          V([], k, function(r) {
            r = ob(n, [r[0], null].concat(r.slice(1)), null, f, g);
            p[b].S === undefined ? (r.Z = c - 1, p[b] = r) : p[b].S[c - 1] = r;
            return [];
          });
          return [];
        });
      },
      p: function(a, b, c, d, e, f) {
        0 < b || x();
        var g = pb(b, c);
        e = Z(d, e);
        V([], [a], function(k) {
          k = k[0];
          var m = "constructor " + k.name;
          k.N.Y === undefined && (k.N.Y = []);
          if (k.N.Y[b - 1] !== undefined)
            throw new K("Cannot register multiple constructors with identical number of parameters (" + (b - 1) + ") for class '" + k.name + "'! Overload resolution is currently only performed using the parameter count, not actual type info!");
          k.N.Y[b - 1] = () => {
            nb("Cannot construct " + k.name + " due to unbound types", g);
          };
          V([], g, function(l) {
            l.splice(1, 0, null);
            k.N.Y[b - 1] = ob(m, l, null, e, f);
            return [];
          });
          return [];
        });
      },
      a: function(a, b, c, d, e, f, g, k) {
        var m = pb(c, d);
        b = N(b);
        f = Z(e, f);
        V([], [a], function(l) {
          function n() {
            nb("Cannot call " + p + " due to unbound types", m);
          }
          l = l[0];
          var p = l.name + "." + b;
          b.startsWith("@@") && (b = Symbol[b.substring(2)]);
          k && l.N.ja.push(b);
          var r = l.N.X, u = r[b];
          u === undefined || u.S === undefined && u.className !== l.name && u.Z === c - 2 ? (n.Z = c - 2, n.className = l.name, r[b] = n) : (ab(r, b, p), r[b].S[c - 2] = n);
          V([], m, function(t) {
            t = ob(p, t, l, f, g);
            r[b].S === undefined ? (t.Z = c - 2, r[b] = t) : r[b].S[c - 2] = t;
            return [];
          });
          return [];
        });
      },
      A: function(a, b) {
        b = N(b);
        W(a, { name: b, fromWireType: function(c) {
          var d = M(c);
          qb(c);
          return d;
        }, toWireType: function(c, d) {
          return Ea(d);
        }, argPackAdvance: 8, readValueFromPointer: Xa, V: null });
      },
      n: function(a, b, c) {
        c = Za(c);
        b = N(b);
        W(a, { name: b, fromWireType: function(d) {
          return d;
        }, toWireType: function(d, e) {
          return e;
        }, argPackAdvance: 8, readValueFromPointer: rb(b, c), V: null });
      },
      e: function(a, b, c, d, e) {
        b = N(b);
        e === -1 && (e = 4294967295);
        e = Za(c);
        var f = (k) => k;
        if (d === 0) {
          var g = 32 - 8 * c;
          f = (k) => k << g >>> g;
        }
        c = b.includes("unsigned") ? function(k, m) {
          return m >>> 0;
        } : function(k, m) {
          return m;
        };
        W(a, { name: b, fromWireType: f, toWireType: c, argPackAdvance: 8, readValueFromPointer: sb(b, e, d !== 0), V: null });
      },
      b: function(a, b, c) {
        function d(f) {
          f >>= 2;
          var g = E;
          return new e(ia, g[f + 1], g[f]);
        }
        var e = [Int8Array, Uint8Array, Int16Array, Uint16Array, Int32Array, Uint32Array, Float32Array, Float64Array][b];
        c = N(c);
        W(a, { name: c, fromWireType: d, argPackAdvance: 8, readValueFromPointer: d }, { ua: true });
      },
      o: function(a, b) {
        b = N(b);
        var c = b === "std::string";
        W(a, { name: b, fromWireType: function(d) {
          var e = E[d >> 2], f = d + 4;
          if (c)
            for (var g = f, k = 0;k <= e; ++k) {
              var m = f + k;
              if (k == e || A[m] == 0) {
                g = g ? z(A, g, m - g) : "";
                if (l === undefined)
                  var l = g;
                else
                  l += String.fromCharCode(0), l += g;
                g = m + 1;
              }
            }
          else {
            l = Array(e);
            for (k = 0;k < e; ++k)
              l[k] = String.fromCharCode(A[f + k]);
            l = l.join("");
          }
          S(d);
          return l;
        }, toWireType: function(d, e) {
          e instanceof ArrayBuffer && (e = new Uint8Array(e));
          var f, g = typeof e == "string";
          g || e instanceof Uint8Array || e instanceof Uint8ClampedArray || e instanceof Int8Array || L("Cannot pass non-string to std::string");
          if (c && g) {
            var k = 0;
            for (f = 0;f < e.length; ++f) {
              var m = e.charCodeAt(f);
              127 >= m ? k++ : 2047 >= m ? k += 2 : 55296 <= m && 57343 >= m ? (k += 4, ++f) : k += 3;
            }
            f = k;
          } else
            f = e.length;
          k = Ib(4 + f + 1);
          m = k + 4;
          E[k >> 2] = f;
          if (c && g) {
            if (g = m, m = f + 1, f = A, 0 < m) {
              m = g + m - 1;
              for (var l = 0;l < e.length; ++l) {
                var n = e.charCodeAt(l);
                if (55296 <= n && 57343 >= n) {
                  var p = e.charCodeAt(++l);
                  n = 65536 + ((n & 1023) << 10) | p & 1023;
                }
                if (127 >= n) {
                  if (g >= m)
                    break;
                  f[g++] = n;
                } else {
                  if (2047 >= n) {
                    if (g + 1 >= m)
                      break;
                    f[g++] = 192 | n >> 6;
                  } else {
                    if (65535 >= n) {
                      if (g + 2 >= m)
                        break;
                      f[g++] = 224 | n >> 12;
                    } else {
                      if (g + 3 >= m)
                        break;
                      f[g++] = 240 | n >> 18;
                      f[g++] = 128 | n >> 12 & 63;
                    }
                    f[g++] = 128 | n >> 6 & 63;
                  }
                  f[g++] = 128 | n & 63;
                }
              }
              f[g] = 0;
            }
          } else if (g)
            for (g = 0;g < f; ++g)
              l = e.charCodeAt(g), 255 < l && (S(m), L("String has UTF-16 code units that do not fit in 8 bits")), A[m + g] = l;
          else
            for (g = 0;g < f; ++g)
              A[m + g] = e[g];
          d !== null && d.push(S, k);
          return k;
        }, argPackAdvance: 8, readValueFromPointer: Xa, V: function(d) {
          S(d);
        } });
      },
      i: function(a, b, c) {
        c = N(c);
        if (b === 2) {
          var d = tb;
          var e = ub;
          var f = vb;
          var g = () => ka;
          var k = 1;
        } else
          b === 4 && (d = wb, e = xb, f = yb, g = () => E, k = 2);
        W(a, { name: c, fromWireType: function(m) {
          for (var l = E[m >> 2], n = g(), p, r = m + 4, u = 0;u <= l; ++u) {
            var t = m + 4 + u * b;
            if (u == l || n[t >> k] == 0)
              r = d(r, t - r), p === undefined ? p = r : (p += String.fromCharCode(0), p += r), r = t + b;
          }
          S(m);
          return p;
        }, toWireType: function(m, l) {
          typeof l != "string" && L("Cannot pass non-string to C++ string type " + c);
          var n = f(l), p = Ib(4 + n + b);
          E[p >> 2] = n >> k;
          e(l, p + 4, n + b);
          m !== null && m.push(S, p);
          return p;
        }, argPackAdvance: 8, readValueFromPointer: Xa, V: function(m) {
          S(m);
        } });
      },
      k: function(a, b, c, d, e, f) {
        Va[a] = { name: N(b), fa: Z(c, d), W: Z(e, f), ia: [] };
      },
      h: function(a, b, c, d, e, f, g, k, m, l) {
        Va[a].ia.push({ oa: N(b), ta: c, ra: Z(d, e), sa: f, za: g, ya: Z(k, m), Aa: l });
      },
      C: function(a, b) {
        b = N(b);
        W(a, {
          va: true,
          name: b,
          argPackAdvance: 0,
          fromWireType: function() {},
          toWireType: function() {}
        });
      },
      s: function(a, b, c, d, e) {
        a = Bb[a];
        b = M(b);
        c = Ab(c);
        var f = [];
        E[d >> 2] = Ea(f);
        return a(b, c, f, e);
      },
      t: function(a, b, c, d) {
        a = Bb[a];
        b = M(b);
        c = Ab(c);
        a(b, c, null, d);
      },
      g: qb,
      m: function(a, b) {
        var c = Db(a, b), d = c[0];
        b = d.name + "_$" + c.slice(1).map(function(g) {
          return g.name;
        }).join("_") + "$";
        var e = Eb[b];
        if (e !== undefined)
          return e;
        var f = Array(a - 1);
        e = Cb((g, k, m, l) => {
          for (var n = 0, p = 0;p < a - 1; ++p)
            f[p] = c[p + 1].readValueFromPointer(l + n), n += c[p + 1].argPackAdvance;
          g = g[k].apply(g, f);
          for (p = 0;p < a - 1; ++p)
            c[p + 1].ma && c[p + 1].ma(f[p]);
          if (!d.va)
            return d.toWireType(m, g);
        });
        return Eb[b] = e;
      },
      D: function(a) {
        4 < a && (J[a].ga += 1);
      },
      r: function(a) {
        var b = M(a);
        Wa(b);
        qb(a);
      },
      c: function() {
        x("");
      },
      x: function(a, b, c) {
        A.copyWithin(a, b, b + c);
      },
      w: function(a) {
        var b = A.length;
        a >>>= 0;
        if (2147483648 < a)
          return false;
        for (var c = 1;4 >= c; c *= 2) {
          var d = b * (1 + 0.2 / c);
          d = Math.min(d, a + 100663296);
          var e = Math;
          d = Math.max(a, d);
          e = e.min.call(e, 2147483648, d + (65536 - d % 65536) % 65536);
          a: {
            try {
              fa.grow(e - ia.byteLength + 65535 >>> 16);
              na();
              var f = 1;
              break a;
            } catch (g) {}
            f = undefined;
          }
          if (f)
            return true;
        }
        return false;
      },
      z: function() {
        return 52;
      },
      u: function() {
        return 70;
      },
      y: function(a, b, c, d) {
        for (var e = 0, f = 0;f < c; f++) {
          var g = E[b >> 2], k = E[b + 4 >> 2];
          b += 8;
          for (var m = 0;m < k; m++) {
            var l = A[g + m], n = Fb[a];
            l === 0 || l === 10 ? ((a === 1 ? ea : v)(z(n, 0)), n.length = 0) : n.push(l);
          }
          e += k;
        }
        E[d >> 2] = e;
        return 0;
      }
    };
    (function() {
      function a(e) {
        h.asm = e.exports;
        fa = h.asm.E;
        na();
        oa = h.asm.J;
        qa.unshift(h.asm.F);
        F--;
        h.monitorRunDependencies && h.monitorRunDependencies(F);
        F == 0 && (ta !== null && (clearInterval(ta), ta = null), G && (e = G, G = null, e()));
      }
      function b(e) {
        a(e.instance);
      }
      function c(e) {
        return ya().then(function(f) {
          return WebAssembly.instantiate(f, d);
        }).then(function(f) {
          return f;
        }).then(e, function(f) {
          v("failed to asynchronously prepare wasm: " + f);
          x(f);
        });
      }
      var d = { a: Jb };
      F++;
      h.monitorRunDependencies && h.monitorRunDependencies(F);
      if (h.instantiateWasm)
        try {
          return h.instantiateWasm(d, a);
        } catch (e) {
          v("Module.instantiateWasm callback failed with error: " + e), ca(e);
        }
      (function() {
        return w || typeof WebAssembly.instantiateStreaming != "function" || ua(H) || typeof fetch != "function" ? c(b) : fetch(H, { credentials: "same-origin" }).then(function(e) {
          return WebAssembly.instantiateStreaming(e, d).then(b, function(f) {
            v("wasm streaming compile failed: " + f);
            v("falling back to ArrayBuffer instantiation");
            return c(b);
          });
        });
      })().catch(ca);
      return {};
    })();
    h.___wasm_call_ctors = function() {
      return (h.___wasm_call_ctors = h.asm.F).apply(null, arguments);
    };
    var Ka = h.___getTypeName = function() {
      return (Ka = h.___getTypeName = h.asm.G).apply(null, arguments);
    };
    h.__embind_initialize_bindings = function() {
      return (h.__embind_initialize_bindings = h.asm.H).apply(null, arguments);
    };
    var Ib = h._malloc = function() {
      return (Ib = h._malloc = h.asm.I).apply(null, arguments);
    }, S = h._free = function() {
      return (S = h._free = h.asm.K).apply(null, arguments);
    };
    h.dynCall_jiji = function() {
      return (h.dynCall_jiji = h.asm.L).apply(null, arguments);
    };
    var Kb;
    G = function Lb() {
      Kb || Mb();
      Kb || (G = Lb);
    };
    function Mb() {
      function a() {
        if (!Kb && (Kb = true, h.calledRun = true, !ha)) {
          za(qa);
          aa(h);
          if (h.onRuntimeInitialized)
            h.onRuntimeInitialized();
          if (h.postRun)
            for (typeof h.postRun == "function" && (h.postRun = [h.postRun]);h.postRun.length; ) {
              var b = h.postRun.shift();
              ra.unshift(b);
            }
          za(ra);
        }
      }
      if (!(0 < F)) {
        if (h.preRun)
          for (typeof h.preRun == "function" && (h.preRun = [h.preRun]);h.preRun.length; )
            sa();
        za(pa);
        0 < F || (h.setStatus ? (h.setStatus("Running..."), setTimeout(function() {
          setTimeout(function() {
            h.setStatus("");
          }, 1);
          a();
        }, 1)) : a());
      }
    }
    if (h.preInit)
      for (typeof h.preInit == "function" && (h.preInit = [h.preInit]);0 < h.preInit.length; )
        h.preInit.pop()();
    Mb();
    return loadYoga2.ready;
  };
})();
var yoga_wasm_base64_esm_default = loadYoga;

// node_modules/yoga-layout/dist/src/generated/YGEnums.js
var Align = /* @__PURE__ */ function(Align2) {
  Align2[Align2["Auto"] = 0] = "Auto";
  Align2[Align2["FlexStart"] = 1] = "FlexStart";
  Align2[Align2["Center"] = 2] = "Center";
  Align2[Align2["FlexEnd"] = 3] = "FlexEnd";
  Align2[Align2["Stretch"] = 4] = "Stretch";
  Align2[Align2["Baseline"] = 5] = "Baseline";
  Align2[Align2["SpaceBetween"] = 6] = "SpaceBetween";
  Align2[Align2["SpaceAround"] = 7] = "SpaceAround";
  Align2[Align2["SpaceEvenly"] = 8] = "SpaceEvenly";
  return Align2;
}({});
var BoxSizing = /* @__PURE__ */ function(BoxSizing2) {
  BoxSizing2[BoxSizing2["BorderBox"] = 0] = "BorderBox";
  BoxSizing2[BoxSizing2["ContentBox"] = 1] = "ContentBox";
  return BoxSizing2;
}({});
var Dimension = /* @__PURE__ */ function(Dimension2) {
  Dimension2[Dimension2["Width"] = 0] = "Width";
  Dimension2[Dimension2["Height"] = 1] = "Height";
  return Dimension2;
}({});
var Direction = /* @__PURE__ */ function(Direction2) {
  Direction2[Direction2["Inherit"] = 0] = "Inherit";
  Direction2[Direction2["LTR"] = 1] = "LTR";
  Direction2[Direction2["RTL"] = 2] = "RTL";
  return Direction2;
}({});
var Display = /* @__PURE__ */ function(Display2) {
  Display2[Display2["Flex"] = 0] = "Flex";
  Display2[Display2["None"] = 1] = "None";
  Display2[Display2["Contents"] = 2] = "Contents";
  return Display2;
}({});
var Edge = /* @__PURE__ */ function(Edge2) {
  Edge2[Edge2["Left"] = 0] = "Left";
  Edge2[Edge2["Top"] = 1] = "Top";
  Edge2[Edge2["Right"] = 2] = "Right";
  Edge2[Edge2["Bottom"] = 3] = "Bottom";
  Edge2[Edge2["Start"] = 4] = "Start";
  Edge2[Edge2["End"] = 5] = "End";
  Edge2[Edge2["Horizontal"] = 6] = "Horizontal";
  Edge2[Edge2["Vertical"] = 7] = "Vertical";
  Edge2[Edge2["All"] = 8] = "All";
  return Edge2;
}({});
var Errata = /* @__PURE__ */ function(Errata2) {
  Errata2[Errata2["None"] = 0] = "None";
  Errata2[Errata2["StretchFlexBasis"] = 1] = "StretchFlexBasis";
  Errata2[Errata2["AbsolutePositionWithoutInsetsExcludesPadding"] = 2] = "AbsolutePositionWithoutInsetsExcludesPadding";
  Errata2[Errata2["AbsolutePercentAgainstInnerSize"] = 4] = "AbsolutePercentAgainstInnerSize";
  Errata2[Errata2["All"] = 2147483647] = "All";
  Errata2[Errata2["Classic"] = 2147483646] = "Classic";
  return Errata2;
}({});
var ExperimentalFeature = /* @__PURE__ */ function(ExperimentalFeature2) {
  ExperimentalFeature2[ExperimentalFeature2["WebFlexBasis"] = 0] = "WebFlexBasis";
  return ExperimentalFeature2;
}({});
var FlexDirection = /* @__PURE__ */ function(FlexDirection2) {
  FlexDirection2[FlexDirection2["Column"] = 0] = "Column";
  FlexDirection2[FlexDirection2["ColumnReverse"] = 1] = "ColumnReverse";
  FlexDirection2[FlexDirection2["Row"] = 2] = "Row";
  FlexDirection2[FlexDirection2["RowReverse"] = 3] = "RowReverse";
  return FlexDirection2;
}({});
var Gutter = /* @__PURE__ */ function(Gutter2) {
  Gutter2[Gutter2["Column"] = 0] = "Column";
  Gutter2[Gutter2["Row"] = 1] = "Row";
  Gutter2[Gutter2["All"] = 2] = "All";
  return Gutter2;
}({});
var Justify = /* @__PURE__ */ function(Justify2) {
  Justify2[Justify2["FlexStart"] = 0] = "FlexStart";
  Justify2[Justify2["Center"] = 1] = "Center";
  Justify2[Justify2["FlexEnd"] = 2] = "FlexEnd";
  Justify2[Justify2["SpaceBetween"] = 3] = "SpaceBetween";
  Justify2[Justify2["SpaceAround"] = 4] = "SpaceAround";
  Justify2[Justify2["SpaceEvenly"] = 5] = "SpaceEvenly";
  return Justify2;
}({});
var LogLevel = /* @__PURE__ */ function(LogLevel2) {
  LogLevel2[LogLevel2["Error"] = 0] = "Error";
  LogLevel2[LogLevel2["Warn"] = 1] = "Warn";
  LogLevel2[LogLevel2["Info"] = 2] = "Info";
  LogLevel2[LogLevel2["Debug"] = 3] = "Debug";
  LogLevel2[LogLevel2["Verbose"] = 4] = "Verbose";
  LogLevel2[LogLevel2["Fatal"] = 5] = "Fatal";
  return LogLevel2;
}({});
var MeasureMode = /* @__PURE__ */ function(MeasureMode2) {
  MeasureMode2[MeasureMode2["Undefined"] = 0] = "Undefined";
  MeasureMode2[MeasureMode2["Exactly"] = 1] = "Exactly";
  MeasureMode2[MeasureMode2["AtMost"] = 2] = "AtMost";
  return MeasureMode2;
}({});
var NodeType = /* @__PURE__ */ function(NodeType2) {
  NodeType2[NodeType2["Default"] = 0] = "Default";
  NodeType2[NodeType2["Text"] = 1] = "Text";
  return NodeType2;
}({});
var Overflow = /* @__PURE__ */ function(Overflow2) {
  Overflow2[Overflow2["Visible"] = 0] = "Visible";
  Overflow2[Overflow2["Hidden"] = 1] = "Hidden";
  Overflow2[Overflow2["Scroll"] = 2] = "Scroll";
  return Overflow2;
}({});
var PositionType = /* @__PURE__ */ function(PositionType2) {
  PositionType2[PositionType2["Static"] = 0] = "Static";
  PositionType2[PositionType2["Relative"] = 1] = "Relative";
  PositionType2[PositionType2["Absolute"] = 2] = "Absolute";
  return PositionType2;
}({});
var Unit = /* @__PURE__ */ function(Unit2) {
  Unit2[Unit2["Undefined"] = 0] = "Undefined";
  Unit2[Unit2["Point"] = 1] = "Point";
  Unit2[Unit2["Percent"] = 2] = "Percent";
  Unit2[Unit2["Auto"] = 3] = "Auto";
  return Unit2;
}({});
var Wrap = /* @__PURE__ */ function(Wrap2) {
  Wrap2[Wrap2["NoWrap"] = 0] = "NoWrap";
  Wrap2[Wrap2["Wrap"] = 1] = "Wrap";
  Wrap2[Wrap2["WrapReverse"] = 2] = "WrapReverse";
  return Wrap2;
}({});
var constants = {
  ALIGN_AUTO: Align.Auto,
  ALIGN_FLEX_START: Align.FlexStart,
  ALIGN_CENTER: Align.Center,
  ALIGN_FLEX_END: Align.FlexEnd,
  ALIGN_STRETCH: Align.Stretch,
  ALIGN_BASELINE: Align.Baseline,
  ALIGN_SPACE_BETWEEN: Align.SpaceBetween,
  ALIGN_SPACE_AROUND: Align.SpaceAround,
  ALIGN_SPACE_EVENLY: Align.SpaceEvenly,
  BOX_SIZING_BORDER_BOX: BoxSizing.BorderBox,
  BOX_SIZING_CONTENT_BOX: BoxSizing.ContentBox,
  DIMENSION_WIDTH: Dimension.Width,
  DIMENSION_HEIGHT: Dimension.Height,
  DIRECTION_INHERIT: Direction.Inherit,
  DIRECTION_LTR: Direction.LTR,
  DIRECTION_RTL: Direction.RTL,
  DISPLAY_FLEX: Display.Flex,
  DISPLAY_NONE: Display.None,
  DISPLAY_CONTENTS: Display.Contents,
  EDGE_LEFT: Edge.Left,
  EDGE_TOP: Edge.Top,
  EDGE_RIGHT: Edge.Right,
  EDGE_BOTTOM: Edge.Bottom,
  EDGE_START: Edge.Start,
  EDGE_END: Edge.End,
  EDGE_HORIZONTAL: Edge.Horizontal,
  EDGE_VERTICAL: Edge.Vertical,
  EDGE_ALL: Edge.All,
  ERRATA_NONE: Errata.None,
  ERRATA_STRETCH_FLEX_BASIS: Errata.StretchFlexBasis,
  ERRATA_ABSOLUTE_POSITION_WITHOUT_INSETS_EXCLUDES_PADDING: Errata.AbsolutePositionWithoutInsetsExcludesPadding,
  ERRATA_ABSOLUTE_PERCENT_AGAINST_INNER_SIZE: Errata.AbsolutePercentAgainstInnerSize,
  ERRATA_ALL: Errata.All,
  ERRATA_CLASSIC: Errata.Classic,
  EXPERIMENTAL_FEATURE_WEB_FLEX_BASIS: ExperimentalFeature.WebFlexBasis,
  FLEX_DIRECTION_COLUMN: FlexDirection.Column,
  FLEX_DIRECTION_COLUMN_REVERSE: FlexDirection.ColumnReverse,
  FLEX_DIRECTION_ROW: FlexDirection.Row,
  FLEX_DIRECTION_ROW_REVERSE: FlexDirection.RowReverse,
  GUTTER_COLUMN: Gutter.Column,
  GUTTER_ROW: Gutter.Row,
  GUTTER_ALL: Gutter.All,
  JUSTIFY_FLEX_START: Justify.FlexStart,
  JUSTIFY_CENTER: Justify.Center,
  JUSTIFY_FLEX_END: Justify.FlexEnd,
  JUSTIFY_SPACE_BETWEEN: Justify.SpaceBetween,
  JUSTIFY_SPACE_AROUND: Justify.SpaceAround,
  JUSTIFY_SPACE_EVENLY: Justify.SpaceEvenly,
  LOG_LEVEL_ERROR: LogLevel.Error,
  LOG_LEVEL_WARN: LogLevel.Warn,
  LOG_LEVEL_INFO: LogLevel.Info,
  LOG_LEVEL_DEBUG: LogLevel.Debug,
  LOG_LEVEL_VERBOSE: LogLevel.Verbose,
  LOG_LEVEL_FATAL: LogLevel.Fatal,
  MEASURE_MODE_UNDEFINED: MeasureMode.Undefined,
  MEASURE_MODE_EXACTLY: MeasureMode.Exactly,
  MEASURE_MODE_AT_MOST: MeasureMode.AtMost,
  NODE_TYPE_DEFAULT: NodeType.Default,
  NODE_TYPE_TEXT: NodeType.Text,
  OVERFLOW_VISIBLE: Overflow.Visible,
  OVERFLOW_HIDDEN: Overflow.Hidden,
  OVERFLOW_SCROLL: Overflow.Scroll,
  POSITION_TYPE_STATIC: PositionType.Static,
  POSITION_TYPE_RELATIVE: PositionType.Relative,
  POSITION_TYPE_ABSOLUTE: PositionType.Absolute,
  UNIT_UNDEFINED: Unit.Undefined,
  UNIT_POINT: Unit.Point,
  UNIT_PERCENT: Unit.Percent,
  UNIT_AUTO: Unit.Auto,
  WRAP_NO_WRAP: Wrap.NoWrap,
  WRAP_WRAP: Wrap.Wrap,
  WRAP_WRAP_REVERSE: Wrap.WrapReverse
};
var YGEnums_default = constants;

// node_modules/yoga-layout/dist/src/wrapAssembly.js
function wrapAssembly(lib) {
  function patch(prototype, name, fn) {
    const original = prototype[name];
    prototype[name] = function() {
      for (var _len = arguments.length, args = new Array(_len), _key = 0;_key < _len; _key++) {
        args[_key] = arguments[_key];
      }
      return fn.call(this, original, ...args);
    };
  }
  for (const fnName of ["setPosition", "setMargin", "setFlexBasis", "setWidth", "setHeight", "setMinWidth", "setMinHeight", "setMaxWidth", "setMaxHeight", "setPadding", "setGap"]) {
    const methods = {
      [Unit.Point]: lib.Node.prototype[fnName],
      [Unit.Percent]: lib.Node.prototype[`${fnName}Percent`],
      [Unit.Auto]: lib.Node.prototype[`${fnName}Auto`]
    };
    patch(lib.Node.prototype, fnName, function(original) {
      for (var _len2 = arguments.length, args = new Array(_len2 > 1 ? _len2 - 1 : 0), _key2 = 1;_key2 < _len2; _key2++) {
        args[_key2 - 1] = arguments[_key2];
      }
      const value = args.pop();
      let unit, asNumber;
      if (value === "auto") {
        unit = Unit.Auto;
        asNumber = undefined;
      } else if (typeof value === "object") {
        unit = value.unit;
        asNumber = value.valueOf();
      } else {
        unit = typeof value === "string" && value.endsWith("%") ? Unit.Percent : Unit.Point;
        asNumber = parseFloat(value);
        if (value !== undefined && !Number.isNaN(value) && Number.isNaN(asNumber)) {
          throw new Error(`Invalid value ${value} for ${fnName}`);
        }
      }
      if (!methods[unit])
        throw new Error(`Failed to execute "${fnName}": Unsupported unit '${value}'`);
      if (asNumber !== undefined) {
        return methods[unit].call(this, ...args, asNumber);
      } else {
        return methods[unit].call(this, ...args);
      }
    });
  }
  function wrapMeasureFunction(measureFunction) {
    return lib.MeasureCallback.implement({
      measure: function() {
        const {
          width,
          height
        } = measureFunction(...arguments);
        return {
          width: width ?? NaN,
          height: height ?? NaN
        };
      }
    });
  }
  patch(lib.Node.prototype, "setMeasureFunc", function(original, measureFunc) {
    if (measureFunc) {
      return original.call(this, wrapMeasureFunction(measureFunc));
    } else {
      return this.unsetMeasureFunc();
    }
  });
  function wrapDirtiedFunc(dirtiedFunction) {
    return lib.DirtiedCallback.implement({
      dirtied: dirtiedFunction
    });
  }
  patch(lib.Node.prototype, "setDirtiedFunc", function(original, dirtiedFunc) {
    original.call(this, wrapDirtiedFunc(dirtiedFunc));
  });
  patch(lib.Config.prototype, "free", function() {
    lib.Config.destroy(this);
  });
  patch(lib.Node, "create", (_, config) => {
    return config ? lib.Node.createWithConfig(config) : lib.Node.createDefault();
  });
  patch(lib.Node.prototype, "free", function() {
    lib.Node.destroy(this);
  });
  patch(lib.Node.prototype, "freeRecursive", function() {
    for (let t = 0, T = this.getChildCount();t < T; ++t) {
      this.getChild(0).freeRecursive();
    }
    this.free();
  });
  patch(lib.Node.prototype, "calculateLayout", function(original) {
    let width = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : NaN;
    let height = arguments.length > 2 && arguments[2] !== undefined ? arguments[2] : NaN;
    let direction = arguments.length > 3 && arguments[3] !== undefined ? arguments[3] : Direction.LTR;
    return original.call(this, width, height, direction);
  });
  return {
    Config: lib.Config,
    Node: lib.Node,
    ...YGEnums_default
  };
}

// node_modules/yoga-layout/dist/src/index.js
var Yoga = wrapAssembly(await yoga_wasm_base64_esm_default());
var src_default = Yoga;

// node_modules/ink/build/reconciler.js
var import_react_reconciler = __toESM(require_react_reconciler(), 1);
var import_constants = __toESM(require_constants(), 1);
import process3 from "node:process";

// node_modules/ansi-regex/index.js
function ansiRegex({ onlyFirst = false } = {}) {
  const ST = "(?:\\u0007|\\u001B\\u005C|\\u009C)";
  const osc = `(?:\\u001B\\][\\s\\S]*?${ST})`;
  const csi = "[\\u001B\\u009B][[\\]()#;?]*(?:\\d{1,4}(?:[;:]\\d{0,4})*)?[\\dA-PR-TZcf-nq-uy=><~]";
  const pattern = `${osc}|${csi}`;
  return new RegExp(pattern, onlyFirst ? undefined : "g");
}

// node_modules/strip-ansi/index.js
var regex = ansiRegex();
function stripAnsi(string) {
  if (typeof string !== "string") {
    throw new TypeError(`Expected a \`string\`, got \`${typeof string}\``);
  }
  if (!string.includes("\x1B") && !string.includes("")) {
    return string;
  }
  return string.replace(regex, "");
}

// node_modules/get-east-asian-width/lookup-data.js
var ambiguousMinimalCodePoint = 161;
var ambiguousMaximumCodePoint = 1114109;
var ambiguousRanges = [161, 161, 164, 164, 167, 168, 170, 170, 173, 174, 176, 180, 182, 186, 188, 191, 198, 198, 208, 208, 215, 216, 222, 225, 230, 230, 232, 234, 236, 237, 240, 240, 242, 243, 247, 250, 252, 252, 254, 254, 257, 257, 273, 273, 275, 275, 283, 283, 294, 295, 299, 299, 305, 307, 312, 312, 319, 322, 324, 324, 328, 331, 333, 333, 338, 339, 358, 359, 363, 363, 462, 462, 464, 464, 466, 466, 468, 468, 470, 470, 472, 472, 474, 474, 476, 476, 593, 593, 609, 609, 708, 708, 711, 711, 713, 715, 717, 717, 720, 720, 728, 731, 733, 733, 735, 735, 768, 879, 913, 929, 931, 937, 945, 961, 963, 969, 1025, 1025, 1040, 1103, 1105, 1105, 8208, 8208, 8211, 8214, 8216, 8217, 8220, 8221, 8224, 8226, 8228, 8231, 8240, 8240, 8242, 8243, 8245, 8245, 8251, 8251, 8254, 8254, 8308, 8308, 8319, 8319, 8321, 8324, 8364, 8364, 8451, 8451, 8453, 8453, 8457, 8457, 8467, 8467, 8470, 8470, 8481, 8482, 8486, 8486, 8491, 8491, 8531, 8532, 8539, 8542, 8544, 8555, 8560, 8569, 8585, 8585, 8592, 8601, 8632, 8633, 8658, 8658, 8660, 8660, 8679, 8679, 8704, 8704, 8706, 8707, 8711, 8712, 8715, 8715, 8719, 8719, 8721, 8721, 8725, 8725, 8730, 8730, 8733, 8736, 8739, 8739, 8741, 8741, 8743, 8748, 8750, 8750, 8756, 8759, 8764, 8765, 8776, 8776, 8780, 8780, 8786, 8786, 8800, 8801, 8804, 8807, 8810, 8811, 8814, 8815, 8834, 8835, 8838, 8839, 8853, 8853, 8857, 8857, 8869, 8869, 8895, 8895, 8978, 8978, 9312, 9449, 9451, 9547, 9552, 9587, 9600, 9615, 9618, 9621, 9632, 9633, 9635, 9641, 9650, 9651, 9654, 9655, 9660, 9661, 9664, 9665, 9670, 9672, 9675, 9675, 9678, 9681, 9698, 9701, 9711, 9711, 9733, 9734, 9737, 9737, 9742, 9743, 9756, 9756, 9758, 9758, 9792, 9792, 9794, 9794, 9824, 9825, 9827, 9829, 9831, 9834, 9836, 9837, 9839, 9839, 9886, 9887, 9919, 9919, 9926, 9933, 9935, 9939, 9941, 9953, 9955, 9955, 9960, 9961, 9963, 9969, 9972, 9972, 9974, 9977, 9979, 9980, 9982, 9983, 10045, 10045, 10102, 10111, 11094, 11097, 12872, 12879, 57344, 63743, 65024, 65039, 65533, 65533, 127232, 127242, 127248, 127277, 127280, 127337, 127344, 127373, 127375, 127376, 127387, 127404, 917760, 917999, 983040, 1048573, 1048576, 1114109];
var fullwidthMinimalCodePoint = 12288;
var fullwidthMaximumCodePoint = 65510;
var fullwidthRanges = [12288, 12288, 65281, 65376, 65504, 65510];
var wideMinimalCodePoint = 4352;
var wideMaximumCodePoint = 262141;
var wideRanges = [4352, 4447, 8986, 8987, 9001, 9002, 9193, 9196, 9200, 9200, 9203, 9203, 9725, 9726, 9748, 9749, 9776, 9783, 9800, 9811, 9855, 9855, 9866, 9871, 9875, 9875, 9889, 9889, 9898, 9899, 9917, 9918, 9924, 9925, 9934, 9934, 9940, 9940, 9962, 9962, 9970, 9971, 9973, 9973, 9978, 9978, 9981, 9981, 9989, 9989, 9994, 9995, 10024, 10024, 10060, 10060, 10062, 10062, 10067, 10069, 10071, 10071, 10133, 10135, 10160, 10160, 10175, 10175, 11035, 11036, 11088, 11088, 11093, 11093, 11904, 11929, 11931, 12019, 12032, 12245, 12272, 12287, 12289, 12350, 12353, 12438, 12441, 12543, 12549, 12591, 12593, 12686, 12688, 12773, 12783, 12830, 12832, 12871, 12880, 42124, 42128, 42182, 43360, 43388, 44032, 55203, 63744, 64255, 65040, 65049, 65072, 65106, 65108, 65126, 65128, 65131, 94176, 94180, 94192, 94198, 94208, 101589, 101631, 101662, 101760, 101874, 110576, 110579, 110581, 110587, 110589, 110590, 110592, 110882, 110898, 110898, 110928, 110930, 110933, 110933, 110948, 110951, 110960, 111355, 119552, 119638, 119648, 119670, 126980, 126980, 127183, 127183, 127374, 127374, 127377, 127386, 127488, 127490, 127504, 127547, 127552, 127560, 127568, 127569, 127584, 127589, 127744, 127776, 127789, 127797, 127799, 127868, 127870, 127891, 127904, 127946, 127951, 127955, 127968, 127984, 127988, 127988, 127992, 128062, 128064, 128064, 128066, 128252, 128255, 128317, 128331, 128334, 128336, 128359, 128378, 128378, 128405, 128406, 128420, 128420, 128507, 128591, 128640, 128709, 128716, 128716, 128720, 128722, 128725, 128728, 128732, 128735, 128747, 128748, 128756, 128764, 128992, 129003, 129008, 129008, 129292, 129338, 129340, 129349, 129351, 129535, 129648, 129660, 129664, 129674, 129678, 129734, 129736, 129736, 129741, 129756, 129759, 129770, 129775, 129784, 131072, 196605, 196608, 262141];

// node_modules/get-east-asian-width/utilities.js
var isInRange = (ranges, codePoint) => {
  let low = 0;
  let high = Math.floor(ranges.length / 2) - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const i = mid * 2;
    if (codePoint < ranges[i]) {
      high = mid - 1;
    } else if (codePoint > ranges[i + 1]) {
      low = mid + 1;
    } else {
      return true;
    }
  }
  return false;
};

// node_modules/get-east-asian-width/lookup.js
var commonCjkCodePoint = 19968;
var [wideFastPathStart, wideFastPathEnd] = /* @__PURE__ */ findWideFastPathRange(wideRanges);
function findWideFastPathRange(ranges) {
  let fastPathStart = ranges[0];
  let fastPathEnd = ranges[1];
  for (let index = 0;index < ranges.length; index += 2) {
    const start = ranges[index];
    const end = ranges[index + 1];
    if (commonCjkCodePoint >= start && commonCjkCodePoint <= end) {
      return [start, end];
    }
    if (end - start > fastPathEnd - fastPathStart) {
      fastPathStart = start;
      fastPathEnd = end;
    }
  }
  return [fastPathStart, fastPathEnd];
}
var isAmbiguous = (codePoint) => {
  if (codePoint < ambiguousMinimalCodePoint || codePoint > ambiguousMaximumCodePoint) {
    return false;
  }
  return isInRange(ambiguousRanges, codePoint);
};
var isFullWidth = (codePoint) => {
  if (codePoint < fullwidthMinimalCodePoint || codePoint > fullwidthMaximumCodePoint) {
    return false;
  }
  return isInRange(fullwidthRanges, codePoint);
};
var isWide = (codePoint) => {
  if (codePoint >= wideFastPathStart && codePoint <= wideFastPathEnd) {
    return true;
  }
  if (codePoint < wideMinimalCodePoint || codePoint > wideMaximumCodePoint) {
    return false;
  }
  return isInRange(wideRanges, codePoint);
};

// node_modules/get-east-asian-width/index.js
function validate(codePoint) {
  if (!Number.isSafeInteger(codePoint)) {
    throw new TypeError(`Expected a code point, got \`${typeof codePoint}\`.`);
  }
}
function eastAsianWidth(codePoint, { ambiguousAsWide = false } = {}) {
  validate(codePoint);
  if (isFullWidth(codePoint) || isWide(codePoint) || ambiguousAsWide && isAmbiguous(codePoint)) {
    return 2;
  }
  return 1;
}

// node_modules/string-width/index.js
var import_emoji_regex = __toESM(require_emoji_regex(), 1);
var segmenter = new Intl.Segmenter;
var defaultIgnorableCodePointRegex = /^\p{Default_Ignorable_Code_Point}$/u;
function stringWidth(string, options = {}) {
  if (typeof string !== "string" || string.length === 0) {
    return 0;
  }
  const {
    ambiguousIsNarrow = true,
    countAnsiEscapeCodes = false
  } = options;
  if (!countAnsiEscapeCodes) {
    string = stripAnsi(string);
  }
  if (string.length === 0) {
    return 0;
  }
  let width = 0;
  const eastAsianWidthOptions = { ambiguousAsWide: !ambiguousIsNarrow };
  for (const { segment: character } of segmenter.segment(string)) {
    const codePoint = character.codePointAt(0);
    if (codePoint <= 31 || codePoint >= 127 && codePoint <= 159) {
      continue;
    }
    if (codePoint >= 8203 && codePoint <= 8207 || codePoint === 65279) {
      continue;
    }
    if (codePoint >= 768 && codePoint <= 879 || codePoint >= 6832 && codePoint <= 6911 || codePoint >= 7616 && codePoint <= 7679 || codePoint >= 8400 && codePoint <= 8447 || codePoint >= 65056 && codePoint <= 65071) {
      continue;
    }
    if (codePoint >= 55296 && codePoint <= 57343) {
      continue;
    }
    if (codePoint >= 65024 && codePoint <= 65039) {
      continue;
    }
    if (defaultIgnorableCodePointRegex.test(character)) {
      continue;
    }
    if (import_emoji_regex.default().test(character)) {
      width += 2;
      continue;
    }
    width += eastAsianWidth(codePoint, eastAsianWidthOptions);
  }
  return width;
}

// node_modules/widest-line/index.js
function widestLine(string) {
  let lineWidth = 0;
  for (const line of string.split(`
`)) {
    lineWidth = Math.max(lineWidth, stringWidth(line));
  }
  return lineWidth;
}

// node_modules/ink/build/measure-text.js
var cache = {};
var measureText = (text) => {
  if (text.length === 0) {
    return {
      width: 0,
      height: 0
    };
  }
  const cachedDimensions = cache[text];
  if (cachedDimensions) {
    return cachedDimensions;
  }
  const width = widestLine(text);
  const height = text.split(`
`).length;
  cache[text] = { width, height };
  return { width, height };
};
var measure_text_default = measureText;

// node_modules/ansi-styles/index.js
var ANSI_BACKGROUND_OFFSET = 10;
var wrapAnsi16 = (offset = 0) => (code) => `\x1B[${code + offset}m`;
var wrapAnsi256 = (offset = 0) => (code) => `\x1B[${38 + offset};5;${code}m`;
var wrapAnsi16m = (offset = 0) => (red, green, blue) => `\x1B[${38 + offset};2;${red};${green};${blue}m`;
var styles = {
  modifier: {
    reset: [0, 0],
    bold: [1, 22],
    dim: [2, 22],
    italic: [3, 23],
    underline: [4, 24],
    overline: [53, 55],
    inverse: [7, 27],
    hidden: [8, 28],
    strikethrough: [9, 29]
  },
  color: {
    black: [30, 39],
    red: [31, 39],
    green: [32, 39],
    yellow: [33, 39],
    blue: [34, 39],
    magenta: [35, 39],
    cyan: [36, 39],
    white: [37, 39],
    blackBright: [90, 39],
    gray: [90, 39],
    grey: [90, 39],
    redBright: [91, 39],
    greenBright: [92, 39],
    yellowBright: [93, 39],
    blueBright: [94, 39],
    magentaBright: [95, 39],
    cyanBright: [96, 39],
    whiteBright: [97, 39]
  },
  bgColor: {
    bgBlack: [40, 49],
    bgRed: [41, 49],
    bgGreen: [42, 49],
    bgYellow: [43, 49],
    bgBlue: [44, 49],
    bgMagenta: [45, 49],
    bgCyan: [46, 49],
    bgWhite: [47, 49],
    bgBlackBright: [100, 49],
    bgGray: [100, 49],
    bgGrey: [100, 49],
    bgRedBright: [101, 49],
    bgGreenBright: [102, 49],
    bgYellowBright: [103, 49],
    bgBlueBright: [104, 49],
    bgMagentaBright: [105, 49],
    bgCyanBright: [106, 49],
    bgWhiteBright: [107, 49]
  }
};
var modifierNames = Object.keys(styles.modifier);
var foregroundColorNames = Object.keys(styles.color);
var backgroundColorNames = Object.keys(styles.bgColor);
var colorNames = [...foregroundColorNames, ...backgroundColorNames];
function assembleStyles() {
  const codes = new Map;
  for (const [groupName, group] of Object.entries(styles)) {
    for (const [styleName, style] of Object.entries(group)) {
      styles[styleName] = {
        open: `\x1B[${style[0]}m`,
        close: `\x1B[${style[1]}m`
      };
      group[styleName] = styles[styleName];
      codes.set(style[0], style[1]);
    }
    Object.defineProperty(styles, groupName, {
      value: group,
      enumerable: false
    });
  }
  Object.defineProperty(styles, "codes", {
    value: codes,
    enumerable: false
  });
  styles.color.close = "\x1B[39m";
  styles.bgColor.close = "\x1B[49m";
  styles.color.ansi = wrapAnsi16();
  styles.color.ansi256 = wrapAnsi256();
  styles.color.ansi16m = wrapAnsi16m();
  styles.bgColor.ansi = wrapAnsi16(ANSI_BACKGROUND_OFFSET);
  styles.bgColor.ansi256 = wrapAnsi256(ANSI_BACKGROUND_OFFSET);
  styles.bgColor.ansi16m = wrapAnsi16m(ANSI_BACKGROUND_OFFSET);
  Object.defineProperties(styles, {
    rgbToAnsi256: {
      value(red, green, blue) {
        if (red === green && green === blue) {
          if (red < 8) {
            return 16;
          }
          if (red > 248) {
            return 231;
          }
          return Math.round((red - 8) / 247 * 24) + 232;
        }
        return 16 + 36 * Math.round(red / 255 * 5) + 6 * Math.round(green / 255 * 5) + Math.round(blue / 255 * 5);
      },
      enumerable: false
    },
    hexToRgb: {
      value(hex) {
        const matches2 = /[a-f\d]{6}|[a-f\d]{3}/i.exec(hex.toString(16));
        if (!matches2) {
          return [0, 0, 0];
        }
        let [colorString] = matches2;
        if (colorString.length === 3) {
          colorString = [...colorString].map((character) => character + character).join("");
        }
        const integer = Number.parseInt(colorString, 16);
        return [
          integer >> 16 & 255,
          integer >> 8 & 255,
          integer & 255
        ];
      },
      enumerable: false
    },
    hexToAnsi256: {
      value: (hex) => styles.rgbToAnsi256(...styles.hexToRgb(hex)),
      enumerable: false
    },
    ansi256ToAnsi: {
      value(code) {
        if (code < 8) {
          return 30 + code;
        }
        if (code < 16) {
          return 90 + (code - 8);
        }
        let red;
        let green;
        let blue;
        if (code >= 232) {
          red = ((code - 232) * 10 + 8) / 255;
          green = red;
          blue = red;
        } else {
          code -= 16;
          const remainder = code % 36;
          red = Math.floor(code / 36) / 5;
          green = Math.floor(remainder / 6) / 5;
          blue = remainder % 6 / 5;
        }
        const value = Math.max(red, green, blue) * 2;
        if (value === 0) {
          return 30;
        }
        let result2 = 30 + (Math.round(blue) << 2 | Math.round(green) << 1 | Math.round(red));
        if (value === 2) {
          result2 += 60;
        }
        return result2;
      },
      enumerable: false
    },
    rgbToAnsi: {
      value: (red, green, blue) => styles.ansi256ToAnsi(styles.rgbToAnsi256(red, green, blue)),
      enumerable: false
    },
    hexToAnsi: {
      value: (hex) => styles.ansi256ToAnsi(styles.hexToAnsi256(hex)),
      enumerable: false
    }
  });
  return styles;
}
var ansiStyles = assembleStyles();
var ansi_styles_default = ansiStyles;

// node_modules/wrap-ansi/index.js
var ESCAPES = new Set([
  "\x1B",
  ""
]);
var END_CODE = 39;
var ANSI_ESCAPE_BELL = "\x07";
var ANSI_CSI = "[";
var ANSI_OSC = "]";
var ANSI_SGR_TERMINATOR = "m";
var ANSI_ESCAPE_LINK = `${ANSI_OSC}8;;`;
var wrapAnsiCode = (code) => `${ESCAPES.values().next().value}${ANSI_CSI}${code}${ANSI_SGR_TERMINATOR}`;
var wrapAnsiHyperlink = (url) => `${ESCAPES.values().next().value}${ANSI_ESCAPE_LINK}${url}${ANSI_ESCAPE_BELL}`;
var wordLengths = (string) => string.split(" ").map((character) => stringWidth(character));
var wrapWord = (rows, word, columns) => {
  const characters = [...word];
  let isInsideEscape = false;
  let isInsideLinkEscape = false;
  let visible = stringWidth(stripAnsi(rows.at(-1)));
  for (const [index, character] of characters.entries()) {
    const characterLength = stringWidth(character);
    if (visible + characterLength <= columns) {
      rows[rows.length - 1] += character;
    } else {
      rows.push(character);
      visible = 0;
    }
    if (ESCAPES.has(character)) {
      isInsideEscape = true;
      const ansiEscapeLinkCandidate = characters.slice(index + 1, index + 1 + ANSI_ESCAPE_LINK.length).join("");
      isInsideLinkEscape = ansiEscapeLinkCandidate === ANSI_ESCAPE_LINK;
    }
    if (isInsideEscape) {
      if (isInsideLinkEscape) {
        if (character === ANSI_ESCAPE_BELL) {
          isInsideEscape = false;
          isInsideLinkEscape = false;
        }
      } else if (character === ANSI_SGR_TERMINATOR) {
        isInsideEscape = false;
      }
      continue;
    }
    visible += characterLength;
    if (visible === columns && index < characters.length - 1) {
      rows.push("");
      visible = 0;
    }
  }
  if (!visible && rows.at(-1).length > 0 && rows.length > 1) {
    rows[rows.length - 2] += rows.pop();
  }
};
var stringVisibleTrimSpacesRight = (string) => {
  const words2 = string.split(" ");
  let last2 = words2.length;
  while (last2 > 0) {
    if (stringWidth(words2[last2 - 1]) > 0) {
      break;
    }
    last2--;
  }
  if (last2 === words2.length) {
    return string;
  }
  return words2.slice(0, last2).join(" ") + words2.slice(last2).join("");
};
var exec = (string, columns, options = {}) => {
  if (options.trim !== false && string.trim() === "") {
    return "";
  }
  let returnValue = "";
  let escapeCode;
  let escapeUrl;
  const lengths = wordLengths(string);
  let rows = [""];
  for (const [index, word] of string.split(" ").entries()) {
    if (options.trim !== false) {
      rows[rows.length - 1] = rows.at(-1).trimStart();
    }
    let rowLength = stringWidth(rows.at(-1));
    if (index !== 0) {
      if (rowLength >= columns && (options.wordWrap === false || options.trim === false)) {
        rows.push("");
        rowLength = 0;
      }
      if (rowLength > 0 || options.trim === false) {
        rows[rows.length - 1] += " ";
        rowLength++;
      }
    }
    if (options.hard && lengths[index] > columns) {
      const remainingColumns = columns - rowLength;
      const breaksStartingThisLine = 1 + Math.floor((lengths[index] - remainingColumns - 1) / columns);
      const breaksStartingNextLine = Math.floor((lengths[index] - 1) / columns);
      if (breaksStartingNextLine < breaksStartingThisLine) {
        rows.push("");
      }
      wrapWord(rows, word, columns);
      continue;
    }
    if (rowLength + lengths[index] > columns && rowLength > 0 && lengths[index] > 0) {
      if (options.wordWrap === false && rowLength < columns) {
        wrapWord(rows, word, columns);
        continue;
      }
      rows.push("");
    }
    if (rowLength + lengths[index] > columns && options.wordWrap === false) {
      wrapWord(rows, word, columns);
      continue;
    }
    rows[rows.length - 1] += word;
  }
  if (options.trim !== false) {
    rows = rows.map((row) => stringVisibleTrimSpacesRight(row));
  }
  const preString = rows.join(`
`);
  const pre = [...preString];
  let preStringIndex = 0;
  for (const [index, character] of pre.entries()) {
    returnValue += character;
    if (ESCAPES.has(character)) {
      const { groups } = new RegExp(`(?:\\${ANSI_CSI}(?<code>\\d+)m|\\${ANSI_ESCAPE_LINK}(?<uri>.*)${ANSI_ESCAPE_BELL})`).exec(preString.slice(preStringIndex)) || { groups: {} };
      if (groups.code !== undefined) {
        const code2 = Number.parseFloat(groups.code);
        escapeCode = code2 === END_CODE ? undefined : code2;
      } else if (groups.uri !== undefined) {
        escapeUrl = groups.uri.length === 0 ? undefined : groups.uri;
      }
    }
    const code = ansi_styles_default.codes.get(Number(escapeCode));
    if (pre[index + 1] === `
`) {
      if (escapeUrl) {
        returnValue += wrapAnsiHyperlink("");
      }
      if (escapeCode && code) {
        returnValue += wrapAnsiCode(code);
      }
    } else if (character === `
`) {
      if (escapeCode && code) {
        returnValue += wrapAnsiCode(escapeCode);
      }
      if (escapeUrl) {
        returnValue += wrapAnsiHyperlink(escapeUrl);
      }
    }
    preStringIndex += character.length;
  }
  return returnValue;
};
function wrapAnsi(string, columns, options) {
  return String(string).normalize().replaceAll(`\r
`, `
`).split(`
`).map((line) => exec(line, columns, options)).join(`
`);
}

// node_modules/is-fullwidth-code-point/index.js
function isFullwidthCodePoint(codePoint) {
  if (!Number.isInteger(codePoint)) {
    return false;
  }
  return codePoint >= 4352 && (codePoint <= 4447 || codePoint === 9001 || codePoint === 9002 || 11904 <= codePoint && codePoint <= 12871 && codePoint !== 12351 || 12880 <= codePoint && codePoint <= 19903 || 19968 <= codePoint && codePoint <= 42182 || 43360 <= codePoint && codePoint <= 43388 || 44032 <= codePoint && codePoint <= 55203 || 63744 <= codePoint && codePoint <= 64255 || 65040 <= codePoint && codePoint <= 65049 || 65072 <= codePoint && codePoint <= 65131 || 65281 <= codePoint && codePoint <= 65376 || 65504 <= codePoint && codePoint <= 65510 || 110592 <= codePoint && codePoint <= 110593 || 127488 <= codePoint && codePoint <= 127569 || 131072 <= codePoint && codePoint <= 262141);
}

// node_modules/cli-truncate/node_modules/slice-ansi/index.js
var astralRegex = /^[\uD800-\uDBFF][\uDC00-\uDFFF]$/;
var ESCAPES2 = [
  "\x1B",
  ""
];
var wrapAnsi2 = (code) => `${ESCAPES2[0]}[${code}m`;
var checkAnsi = (ansiCodes, isEscapes, endAnsiCode) => {
  let output = [];
  ansiCodes = [...ansiCodes];
  for (let ansiCode of ansiCodes) {
    const ansiCodeOrigin = ansiCode;
    if (ansiCode.includes(";")) {
      ansiCode = ansiCode.split(";")[0][0] + "0";
    }
    const item = ansi_styles_default.codes.get(Number.parseInt(ansiCode, 10));
    if (item) {
      const indexEscape = ansiCodes.indexOf(item.toString());
      if (indexEscape === -1) {
        output.push(wrapAnsi2(isEscapes ? item : ansiCodeOrigin));
      } else {
        ansiCodes.splice(indexEscape, 1);
      }
    } else if (isEscapes) {
      output.push(wrapAnsi2(0));
      break;
    } else {
      output.push(wrapAnsi2(ansiCodeOrigin));
    }
  }
  if (isEscapes) {
    output = output.filter((element, index) => output.indexOf(element) === index);
    if (endAnsiCode !== undefined) {
      const fistEscapeCode = wrapAnsi2(ansi_styles_default.codes.get(Number.parseInt(endAnsiCode, 10)));
      output = output.reduce((current, next) => next === fistEscapeCode ? [next, ...current] : [...current, next], []);
    }
  }
  return output.join("");
};
function sliceAnsi(string, begin, end) {
  const characters = [...string];
  const ansiCodes = [];
  let stringEnd = typeof end === "number" ? end : characters.length;
  let isInsideEscape = false;
  let ansiCode;
  let visible = 0;
  let output = "";
  for (const [index, character] of characters.entries()) {
    let leftEscape = false;
    if (ESCAPES2.includes(character)) {
      const code = /\d[^m]*/.exec(string.slice(index, index + 18));
      ansiCode = code && code.length > 0 ? code[0] : undefined;
      if (visible < stringEnd) {
        isInsideEscape = true;
        if (ansiCode !== undefined) {
          ansiCodes.push(ansiCode);
        }
      }
    } else if (isInsideEscape && character === "m") {
      isInsideEscape = false;
      leftEscape = true;
    }
    if (!isInsideEscape && !leftEscape) {
      visible++;
    }
    if (!astralRegex.test(character) && isFullwidthCodePoint(character.codePointAt())) {
      visible++;
      if (typeof end !== "number") {
        stringEnd++;
      }
    }
    if (visible > begin && visible <= stringEnd) {
      output += character;
    } else if (visible === begin && !isInsideEscape && ansiCode !== undefined) {
      output = checkAnsi(ansiCodes);
    } else if (visible >= stringEnd) {
      output += checkAnsi(ansiCodes, true, ansiCode);
      break;
    }
  }
  return output;
}

// node_modules/cli-truncate/index.js
function getIndexOfNearestSpace(string, wantedIndex, shouldSearchRight) {
  if (string.charAt(wantedIndex) === " ") {
    return wantedIndex;
  }
  const direction = shouldSearchRight ? 1 : -1;
  for (let index = 0;index <= 3; index++) {
    const finalIndex = wantedIndex + index * direction;
    if (string.charAt(finalIndex) === " ") {
      return finalIndex;
    }
  }
  return wantedIndex;
}
function cliTruncate(text, columns, options = {}) {
  const {
    position = "end",
    space = false,
    preferTruncationOnSpace = false
  } = options;
  let { truncationCharacter = "…" } = options;
  if (typeof text !== "string") {
    throw new TypeError(`Expected \`input\` to be a string, got ${typeof text}`);
  }
  if (typeof columns !== "number") {
    throw new TypeError(`Expected \`columns\` to be a number, got ${typeof columns}`);
  }
  if (columns < 1) {
    return "";
  }
  if (columns === 1) {
    return truncationCharacter;
  }
  const length = stringWidth(text);
  if (length <= columns) {
    return text;
  }
  if (position === "start") {
    if (preferTruncationOnSpace) {
      const nearestSpace = getIndexOfNearestSpace(text, length - columns + 1, true);
      return truncationCharacter + sliceAnsi(text, nearestSpace, length).trim();
    }
    if (space === true) {
      truncationCharacter += " ";
    }
    return truncationCharacter + sliceAnsi(text, length - columns + stringWidth(truncationCharacter), length);
  }
  if (position === "middle") {
    if (space === true) {
      truncationCharacter = ` ${truncationCharacter} `;
    }
    const half = Math.floor(columns / 2);
    if (preferTruncationOnSpace) {
      const spaceNearFirstBreakPoint = getIndexOfNearestSpace(text, half);
      const spaceNearSecondBreakPoint = getIndexOfNearestSpace(text, length - (columns - half) + 1, true);
      return sliceAnsi(text, 0, spaceNearFirstBreakPoint) + truncationCharacter + sliceAnsi(text, spaceNearSecondBreakPoint, length).trim();
    }
    return sliceAnsi(text, 0, half) + truncationCharacter + sliceAnsi(text, length - (columns - half) + stringWidth(truncationCharacter), length);
  }
  if (position === "end") {
    if (preferTruncationOnSpace) {
      const nearestSpace = getIndexOfNearestSpace(text, columns - 1);
      return sliceAnsi(text, 0, nearestSpace) + truncationCharacter;
    }
    if (space === true) {
      truncationCharacter = ` ${truncationCharacter}`;
    }
    return sliceAnsi(text, 0, columns - stringWidth(truncationCharacter)) + truncationCharacter;
  }
  throw new Error(`Expected \`options.position\` to be either \`start\`, \`middle\` or \`end\`, got ${position}`);
}

// node_modules/ink/build/wrap-text.js
var cache2 = {};
var wrapText = (text, maxWidth, wrapType) => {
  const cacheKey = text + String(maxWidth) + String(wrapType);
  const cachedText = cache2[cacheKey];
  if (cachedText) {
    return cachedText;
  }
  let wrappedText = text;
  if (wrapType === "wrap") {
    wrappedText = wrapAnsi(text, maxWidth, {
      trim: false,
      hard: true
    });
  }
  if (wrapType.startsWith("truncate")) {
    let position = "end";
    if (wrapType === "truncate-middle") {
      position = "middle";
    }
    if (wrapType === "truncate-start") {
      position = "start";
    }
    wrappedText = cliTruncate(text, maxWidth, { position });
  }
  cache2[cacheKey] = wrappedText;
  return wrappedText;
};
var wrap_text_default = wrapText;

// node_modules/ink/build/squash-text-nodes.js
var squashTextNodes = (node) => {
  let text = "";
  for (let index = 0;index < node.childNodes.length; index++) {
    const childNode = node.childNodes[index];
    if (childNode === undefined) {
      continue;
    }
    let nodeText = "";
    if (childNode.nodeName === "#text") {
      nodeText = childNode.nodeValue;
    } else {
      if (childNode.nodeName === "ink-text" || childNode.nodeName === "ink-virtual-text") {
        nodeText = squashTextNodes(childNode);
      }
      if (nodeText.length > 0 && typeof childNode.internal_transform === "function") {
        nodeText = childNode.internal_transform(nodeText, index);
      }
    }
    text += nodeText;
  }
  return text;
};
var squash_text_nodes_default = squashTextNodes;

// node_modules/ink/build/dom.js
var createNode = (nodeName) => {
  const node = {
    nodeName,
    style: {},
    attributes: {},
    childNodes: [],
    parentNode: undefined,
    yogaNode: nodeName === "ink-virtual-text" ? undefined : src_default.Node.create()
  };
  if (nodeName === "ink-text") {
    node.yogaNode?.setMeasureFunc(measureTextNode.bind(null, node));
  }
  return node;
};
var appendChildNode = (node, childNode) => {
  if (childNode.parentNode) {
    removeChildNode(childNode.parentNode, childNode);
  }
  childNode.parentNode = node;
  node.childNodes.push(childNode);
  if (childNode.yogaNode) {
    node.yogaNode?.insertChild(childNode.yogaNode, node.yogaNode.getChildCount());
  }
  if (node.nodeName === "ink-text" || node.nodeName === "ink-virtual-text") {
    markNodeAsDirty(node);
  }
};
var insertBeforeNode = (node, newChildNode, beforeChildNode) => {
  if (newChildNode.parentNode) {
    removeChildNode(newChildNode.parentNode, newChildNode);
  }
  newChildNode.parentNode = node;
  const index = node.childNodes.indexOf(beforeChildNode);
  if (index >= 0) {
    node.childNodes.splice(index, 0, newChildNode);
    if (newChildNode.yogaNode) {
      node.yogaNode?.insertChild(newChildNode.yogaNode, index);
    }
    return;
  }
  node.childNodes.push(newChildNode);
  if (newChildNode.yogaNode) {
    node.yogaNode?.insertChild(newChildNode.yogaNode, node.yogaNode.getChildCount());
  }
  if (node.nodeName === "ink-text" || node.nodeName === "ink-virtual-text") {
    markNodeAsDirty(node);
  }
};
var removeChildNode = (node, removeNode) => {
  if (removeNode.yogaNode) {
    removeNode.parentNode?.yogaNode?.removeChild(removeNode.yogaNode);
  }
  removeNode.parentNode = undefined;
  const index = node.childNodes.indexOf(removeNode);
  if (index >= 0) {
    node.childNodes.splice(index, 1);
  }
  if (node.nodeName === "ink-text" || node.nodeName === "ink-virtual-text") {
    markNodeAsDirty(node);
  }
};
var setAttribute = (node, key, value) => {
  node.attributes[key] = value;
};
var setStyle = (node, style) => {
  node.style = style;
};
var createTextNode = (text) => {
  const node = {
    nodeName: "#text",
    nodeValue: text,
    yogaNode: undefined,
    parentNode: undefined,
    style: {}
  };
  setTextNodeValue(node, text);
  return node;
};
var measureTextNode = function(node, width) {
  const text = node.nodeName === "#text" ? node.nodeValue : squash_text_nodes_default(node);
  const dimensions = measure_text_default(text);
  if (dimensions.width <= width) {
    return dimensions;
  }
  if (dimensions.width >= 1 && width > 0 && width < 1) {
    return dimensions;
  }
  const textWrap = node.style?.textWrap ?? "wrap";
  const wrappedText = wrap_text_default(text, width, textWrap);
  return measure_text_default(wrappedText);
};
var findClosestYogaNode = (node) => {
  if (!node?.parentNode) {
    return;
  }
  return node.yogaNode ?? findClosestYogaNode(node.parentNode);
};
var markNodeAsDirty = (node) => {
  const yogaNode = findClosestYogaNode(node);
  yogaNode?.markDirty();
};
var setTextNodeValue = (node, text) => {
  if (typeof text !== "string") {
    text = String(text);
  }
  node.nodeValue = text;
  markNodeAsDirty(node);
};

// node_modules/ink/build/styles.js
var applyPositionStyles = (node, style) => {
  if ("position" in style) {
    node.setPositionType(style.position === "absolute" ? src_default.POSITION_TYPE_ABSOLUTE : src_default.POSITION_TYPE_RELATIVE);
  }
};
var applyMarginStyles = (node, style) => {
  if ("margin" in style) {
    node.setMargin(src_default.EDGE_ALL, style.margin ?? 0);
  }
  if ("marginX" in style) {
    node.setMargin(src_default.EDGE_HORIZONTAL, style.marginX ?? 0);
  }
  if ("marginY" in style) {
    node.setMargin(src_default.EDGE_VERTICAL, style.marginY ?? 0);
  }
  if ("marginLeft" in style) {
    node.setMargin(src_default.EDGE_START, style.marginLeft || 0);
  }
  if ("marginRight" in style) {
    node.setMargin(src_default.EDGE_END, style.marginRight || 0);
  }
  if ("marginTop" in style) {
    node.setMargin(src_default.EDGE_TOP, style.marginTop || 0);
  }
  if ("marginBottom" in style) {
    node.setMargin(src_default.EDGE_BOTTOM, style.marginBottom || 0);
  }
};
var applyPaddingStyles = (node, style) => {
  if ("padding" in style) {
    node.setPadding(src_default.EDGE_ALL, style.padding ?? 0);
  }
  if ("paddingX" in style) {
    node.setPadding(src_default.EDGE_HORIZONTAL, style.paddingX ?? 0);
  }
  if ("paddingY" in style) {
    node.setPadding(src_default.EDGE_VERTICAL, style.paddingY ?? 0);
  }
  if ("paddingLeft" in style) {
    node.setPadding(src_default.EDGE_LEFT, style.paddingLeft || 0);
  }
  if ("paddingRight" in style) {
    node.setPadding(src_default.EDGE_RIGHT, style.paddingRight || 0);
  }
  if ("paddingTop" in style) {
    node.setPadding(src_default.EDGE_TOP, style.paddingTop || 0);
  }
  if ("paddingBottom" in style) {
    node.setPadding(src_default.EDGE_BOTTOM, style.paddingBottom || 0);
  }
};
var applyFlexStyles = (node, style) => {
  if ("flexGrow" in style) {
    node.setFlexGrow(style.flexGrow ?? 0);
  }
  if ("flexShrink" in style) {
    node.setFlexShrink(typeof style.flexShrink === "number" ? style.flexShrink : 1);
  }
  if ("flexWrap" in style) {
    if (style.flexWrap === "nowrap") {
      node.setFlexWrap(src_default.WRAP_NO_WRAP);
    }
    if (style.flexWrap === "wrap") {
      node.setFlexWrap(src_default.WRAP_WRAP);
    }
    if (style.flexWrap === "wrap-reverse") {
      node.setFlexWrap(src_default.WRAP_WRAP_REVERSE);
    }
  }
  if ("flexDirection" in style) {
    if (style.flexDirection === "row") {
      node.setFlexDirection(src_default.FLEX_DIRECTION_ROW);
    }
    if (style.flexDirection === "row-reverse") {
      node.setFlexDirection(src_default.FLEX_DIRECTION_ROW_REVERSE);
    }
    if (style.flexDirection === "column") {
      node.setFlexDirection(src_default.FLEX_DIRECTION_COLUMN);
    }
    if (style.flexDirection === "column-reverse") {
      node.setFlexDirection(src_default.FLEX_DIRECTION_COLUMN_REVERSE);
    }
  }
  if ("flexBasis" in style) {
    if (typeof style.flexBasis === "number") {
      node.setFlexBasis(style.flexBasis);
    } else if (typeof style.flexBasis === "string") {
      node.setFlexBasisPercent(Number.parseInt(style.flexBasis, 10));
    } else {
      node.setFlexBasis(Number.NaN);
    }
  }
  if ("alignItems" in style) {
    if (style.alignItems === "stretch" || !style.alignItems) {
      node.setAlignItems(src_default.ALIGN_STRETCH);
    }
    if (style.alignItems === "flex-start") {
      node.setAlignItems(src_default.ALIGN_FLEX_START);
    }
    if (style.alignItems === "center") {
      node.setAlignItems(src_default.ALIGN_CENTER);
    }
    if (style.alignItems === "flex-end") {
      node.setAlignItems(src_default.ALIGN_FLEX_END);
    }
  }
  if ("alignSelf" in style) {
    if (style.alignSelf === "auto" || !style.alignSelf) {
      node.setAlignSelf(src_default.ALIGN_AUTO);
    }
    if (style.alignSelf === "flex-start") {
      node.setAlignSelf(src_default.ALIGN_FLEX_START);
    }
    if (style.alignSelf === "center") {
      node.setAlignSelf(src_default.ALIGN_CENTER);
    }
    if (style.alignSelf === "flex-end") {
      node.setAlignSelf(src_default.ALIGN_FLEX_END);
    }
  }
  if ("justifyContent" in style) {
    if (style.justifyContent === "flex-start" || !style.justifyContent) {
      node.setJustifyContent(src_default.JUSTIFY_FLEX_START);
    }
    if (style.justifyContent === "center") {
      node.setJustifyContent(src_default.JUSTIFY_CENTER);
    }
    if (style.justifyContent === "flex-end") {
      node.setJustifyContent(src_default.JUSTIFY_FLEX_END);
    }
    if (style.justifyContent === "space-between") {
      node.setJustifyContent(src_default.JUSTIFY_SPACE_BETWEEN);
    }
    if (style.justifyContent === "space-around") {
      node.setJustifyContent(src_default.JUSTIFY_SPACE_AROUND);
    }
    if (style.justifyContent === "space-evenly") {
      node.setJustifyContent(src_default.JUSTIFY_SPACE_EVENLY);
    }
  }
};
var applyDimensionStyles = (node, style) => {
  if ("width" in style) {
    if (typeof style.width === "number") {
      node.setWidth(style.width);
    } else if (typeof style.width === "string") {
      node.setWidthPercent(Number.parseInt(style.width, 10));
    } else {
      node.setWidthAuto();
    }
  }
  if ("height" in style) {
    if (typeof style.height === "number") {
      node.setHeight(style.height);
    } else if (typeof style.height === "string") {
      node.setHeightPercent(Number.parseInt(style.height, 10));
    } else {
      node.setHeightAuto();
    }
  }
  if ("minWidth" in style) {
    if (typeof style.minWidth === "string") {
      node.setMinWidthPercent(Number.parseInt(style.minWidth, 10));
    } else {
      node.setMinWidth(style.minWidth ?? 0);
    }
  }
  if ("minHeight" in style) {
    if (typeof style.minHeight === "string") {
      node.setMinHeightPercent(Number.parseInt(style.minHeight, 10));
    } else {
      node.setMinHeight(style.minHeight ?? 0);
    }
  }
};
var applyDisplayStyles = (node, style) => {
  if ("display" in style) {
    node.setDisplay(style.display === "flex" ? src_default.DISPLAY_FLEX : src_default.DISPLAY_NONE);
  }
};
var applyBorderStyles = (node, style) => {
  if ("borderStyle" in style) {
    const borderWidth = style.borderStyle ? 1 : 0;
    if (style.borderTop !== false) {
      node.setBorder(src_default.EDGE_TOP, borderWidth);
    }
    if (style.borderBottom !== false) {
      node.setBorder(src_default.EDGE_BOTTOM, borderWidth);
    }
    if (style.borderLeft !== false) {
      node.setBorder(src_default.EDGE_LEFT, borderWidth);
    }
    if (style.borderRight !== false) {
      node.setBorder(src_default.EDGE_RIGHT, borderWidth);
    }
  }
};
var applyGapStyles = (node, style) => {
  if ("gap" in style) {
    node.setGap(src_default.GUTTER_ALL, style.gap ?? 0);
  }
  if ("columnGap" in style) {
    node.setGap(src_default.GUTTER_COLUMN, style.columnGap ?? 0);
  }
  if ("rowGap" in style) {
    node.setGap(src_default.GUTTER_ROW, style.rowGap ?? 0);
  }
};
var styles2 = (node, style = {}) => {
  applyPositionStyles(node, style);
  applyMarginStyles(node, style);
  applyPaddingStyles(node, style);
  applyFlexStyles(node, style);
  applyDimensionStyles(node, style);
  applyDisplayStyles(node, style);
  applyBorderStyles(node, style);
  applyGapStyles(node, style);
};
var styles_default = styles2;

// node_modules/ink/build/reconciler.js
if (process3.env["DEV"] === "true") {
  try {
    await Promise.resolve().then(() => (init_devtools(), exports_devtools));
  } catch (error) {
    if (error.code === "ERR_MODULE_NOT_FOUND") {
      console.warn(`
The environment variable DEV is set to true, so Ink tried to import \`react-devtools-core\`,
but this failed as it was not installed. Debugging with React Devtools requires it.

To install use this command:

$ npm install --save-dev react-devtools-core
				`.trim() + `
`);
    } else {
      throw error;
    }
  }
}
var diff = (before2, after2) => {
  if (before2 === after2) {
    return;
  }
  if (!before2) {
    return after2;
  }
  const changed = {};
  let isChanged = false;
  for (const key of Object.keys(before2)) {
    const isDeleted = after2 ? !Object.hasOwn(after2, key) : true;
    if (isDeleted) {
      changed[key] = undefined;
      isChanged = true;
    }
  }
  if (after2) {
    for (const key of Object.keys(after2)) {
      if (after2[key] !== before2[key]) {
        changed[key] = after2[key];
        isChanged = true;
      }
    }
  }
  return isChanged ? changed : undefined;
};
var cleanupYogaNode = (node) => {
  node?.unsetMeasureFunc();
  node?.freeRecursive();
};
var reconciler_default = import_react_reconciler.default({
  getRootHostContext: () => ({
    isInsideText: false
  }),
  prepareForCommit: () => null,
  preparePortalMount: () => null,
  clearContainer: () => false,
  resetAfterCommit(rootNode) {
    if (typeof rootNode.onComputeLayout === "function") {
      rootNode.onComputeLayout();
    }
    if (rootNode.isStaticDirty) {
      rootNode.isStaticDirty = false;
      if (typeof rootNode.onImmediateRender === "function") {
        rootNode.onImmediateRender();
      }
      return;
    }
    if (typeof rootNode.onRender === "function") {
      rootNode.onRender();
    }
  },
  getChildHostContext(parentHostContext, type) {
    const previousIsInsideText = parentHostContext.isInsideText;
    const isInsideText = type === "ink-text" || type === "ink-virtual-text";
    if (previousIsInsideText === isInsideText) {
      return parentHostContext;
    }
    return { isInsideText };
  },
  shouldSetTextContent: () => false,
  createInstance(originalType, newProps, _root, hostContext) {
    if (hostContext.isInsideText && originalType === "ink-box") {
      throw new Error(`<Box> can’t be nested inside <Text> component`);
    }
    const type = originalType === "ink-text" && hostContext.isInsideText ? "ink-virtual-text" : originalType;
    const node = createNode(type);
    for (const [key, value] of Object.entries(newProps)) {
      if (key === "children") {
        continue;
      }
      if (key === "style") {
        setStyle(node, value);
        if (node.yogaNode) {
          styles_default(node.yogaNode, value);
        }
        continue;
      }
      if (key === "internal_transform") {
        node.internal_transform = value;
        continue;
      }
      if (key === "internal_static") {
        node.internal_static = true;
        continue;
      }
      setAttribute(node, key, value);
    }
    return node;
  },
  createTextInstance(text, _root, hostContext) {
    if (!hostContext.isInsideText) {
      throw new Error(`Text string "${text}" must be rendered inside <Text> component`);
    }
    return createTextNode(text);
  },
  resetTextContent() {},
  hideTextInstance(node) {
    setTextNodeValue(node, "");
  },
  unhideTextInstance(node, text) {
    setTextNodeValue(node, text);
  },
  getPublicInstance: (instance) => instance,
  hideInstance(node) {
    node.yogaNode?.setDisplay(src_default.DISPLAY_NONE);
  },
  unhideInstance(node) {
    node.yogaNode?.setDisplay(src_default.DISPLAY_FLEX);
  },
  appendInitialChild: appendChildNode,
  appendChild: appendChildNode,
  insertBefore: insertBeforeNode,
  finalizeInitialChildren(node, _type, _props, rootNode) {
    if (node.internal_static) {
      rootNode.isStaticDirty = true;
      rootNode.staticNode = node;
    }
    return false;
  },
  isPrimaryRenderer: true,
  supportsMutation: true,
  supportsPersistence: false,
  supportsHydration: false,
  scheduleTimeout: setTimeout,
  cancelTimeout: clearTimeout,
  noTimeout: -1,
  getCurrentEventPriority: () => import_constants.DefaultEventPriority,
  beforeActiveInstanceBlur() {},
  afterActiveInstanceBlur() {},
  detachDeletedInstance() {},
  getInstanceFromNode: () => null,
  prepareScopeUpdate() {},
  getInstanceFromScope: () => null,
  appendChildToContainer: appendChildNode,
  insertInContainerBefore: insertBeforeNode,
  removeChildFromContainer(node, removeNode) {
    removeChildNode(node, removeNode);
    cleanupYogaNode(removeNode.yogaNode);
  },
  prepareUpdate(node, _type, oldProps, newProps, rootNode) {
    if (node.internal_static) {
      rootNode.isStaticDirty = true;
    }
    const props = diff(oldProps, newProps);
    const style = diff(oldProps["style"], newProps["style"]);
    if (!props && !style) {
      return null;
    }
    return { props, style };
  },
  commitUpdate(node, { props, style }) {
    if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (key === "style") {
          setStyle(node, value);
          continue;
        }
        if (key === "internal_transform") {
          node.internal_transform = value;
          continue;
        }
        if (key === "internal_static") {
          node.internal_static = true;
          continue;
        }
        setAttribute(node, key, value);
      }
    }
    if (style && node.yogaNode) {
      styles_default(node.yogaNode, style);
    }
  },
  commitTextUpdate(node, _oldText, newText) {
    setTextNodeValue(node, newText);
  },
  removeChild(node, removeNode) {
    removeChildNode(node, removeNode);
    cleanupYogaNode(removeNode.yogaNode);
  }
});

// node_modules/indent-string/index.js
function indentString(string, count = 1, options = {}) {
  const {
    indent = " ",
    includeEmptyLines = false
  } = options;
  if (typeof string !== "string") {
    throw new TypeError(`Expected \`input\` to be a \`string\`, got \`${typeof string}\``);
  }
  if (typeof count !== "number") {
    throw new TypeError(`Expected \`count\` to be a \`number\`, got \`${typeof count}\``);
  }
  if (count < 0) {
    throw new RangeError(`Expected \`count\` to be at least 0, got \`${count}\``);
  }
  if (typeof indent !== "string") {
    throw new TypeError(`Expected \`options.indent\` to be a \`string\`, got \`${typeof indent}\``);
  }
  if (count === 0) {
    return string;
  }
  const regex2 = includeEmptyLines ? /^/gm : /^(?!\s*$)/gm;
  return string.replace(regex2, indent.repeat(count));
}

// node_modules/ink/build/get-max-width.js
var getMaxWidth = (yogaNode) => {
  return yogaNode.getComputedWidth() - yogaNode.getComputedPadding(src_default.EDGE_LEFT) - yogaNode.getComputedPadding(src_default.EDGE_RIGHT) - yogaNode.getComputedBorder(src_default.EDGE_LEFT) - yogaNode.getComputedBorder(src_default.EDGE_RIGHT);
};
var get_max_width_default = getMaxWidth;

// node_modules/ink/build/render-border.js
var import_cli_boxes = __toESM(require_cli_boxes(), 1);

// node_modules/chalk/source/vendor/ansi-styles/index.js
var ANSI_BACKGROUND_OFFSET2 = 10;
var wrapAnsi162 = (offset = 0) => (code) => `\x1B[${code + offset}m`;
var wrapAnsi2562 = (offset = 0) => (code) => `\x1B[${38 + offset};5;${code}m`;
var wrapAnsi16m2 = (offset = 0) => (red, green, blue) => `\x1B[${38 + offset};2;${red};${green};${blue}m`;
var styles3 = {
  modifier: {
    reset: [0, 0],
    bold: [1, 22],
    dim: [2, 22],
    italic: [3, 23],
    underline: [4, 24],
    overline: [53, 55],
    inverse: [7, 27],
    hidden: [8, 28],
    strikethrough: [9, 29]
  },
  color: {
    black: [30, 39],
    red: [31, 39],
    green: [32, 39],
    yellow: [33, 39],
    blue: [34, 39],
    magenta: [35, 39],
    cyan: [36, 39],
    white: [37, 39],
    blackBright: [90, 39],
    gray: [90, 39],
    grey: [90, 39],
    redBright: [91, 39],
    greenBright: [92, 39],
    yellowBright: [93, 39],
    blueBright: [94, 39],
    magentaBright: [95, 39],
    cyanBright: [96, 39],
    whiteBright: [97, 39]
  },
  bgColor: {
    bgBlack: [40, 49],
    bgRed: [41, 49],
    bgGreen: [42, 49],
    bgYellow: [43, 49],
    bgBlue: [44, 49],
    bgMagenta: [45, 49],
    bgCyan: [46, 49],
    bgWhite: [47, 49],
    bgBlackBright: [100, 49],
    bgGray: [100, 49],
    bgGrey: [100, 49],
    bgRedBright: [101, 49],
    bgGreenBright: [102, 49],
    bgYellowBright: [103, 49],
    bgBlueBright: [104, 49],
    bgMagentaBright: [105, 49],
    bgCyanBright: [106, 49],
    bgWhiteBright: [107, 49]
  }
};
var modifierNames2 = Object.keys(styles3.modifier);
var foregroundColorNames2 = Object.keys(styles3.color);
var backgroundColorNames2 = Object.keys(styles3.bgColor);
var colorNames2 = [...foregroundColorNames2, ...backgroundColorNames2];
function assembleStyles2() {
  const codes = new Map;
  for (const [groupName, group] of Object.entries(styles3)) {
    for (const [styleName, style] of Object.entries(group)) {
      styles3[styleName] = {
        open: `\x1B[${style[0]}m`,
        close: `\x1B[${style[1]}m`
      };
      group[styleName] = styles3[styleName];
      codes.set(style[0], style[1]);
    }
    Object.defineProperty(styles3, groupName, {
      value: group,
      enumerable: false
    });
  }
  Object.defineProperty(styles3, "codes", {
    value: codes,
    enumerable: false
  });
  styles3.color.close = "\x1B[39m";
  styles3.bgColor.close = "\x1B[49m";
  styles3.color.ansi = wrapAnsi162();
  styles3.color.ansi256 = wrapAnsi2562();
  styles3.color.ansi16m = wrapAnsi16m2();
  styles3.bgColor.ansi = wrapAnsi162(ANSI_BACKGROUND_OFFSET2);
  styles3.bgColor.ansi256 = wrapAnsi2562(ANSI_BACKGROUND_OFFSET2);
  styles3.bgColor.ansi16m = wrapAnsi16m2(ANSI_BACKGROUND_OFFSET2);
  Object.defineProperties(styles3, {
    rgbToAnsi256: {
      value(red, green, blue) {
        if (red === green && green === blue) {
          if (red < 8) {
            return 16;
          }
          if (red > 248) {
            return 231;
          }
          return Math.round((red - 8) / 247 * 24) + 232;
        }
        return 16 + 36 * Math.round(red / 255 * 5) + 6 * Math.round(green / 255 * 5) + Math.round(blue / 255 * 5);
      },
      enumerable: false
    },
    hexToRgb: {
      value(hex) {
        const matches2 = /[a-f\d]{6}|[a-f\d]{3}/i.exec(hex.toString(16));
        if (!matches2) {
          return [0, 0, 0];
        }
        let [colorString] = matches2;
        if (colorString.length === 3) {
          colorString = [...colorString].map((character) => character + character).join("");
        }
        const integer = Number.parseInt(colorString, 16);
        return [
          integer >> 16 & 255,
          integer >> 8 & 255,
          integer & 255
        ];
      },
      enumerable: false
    },
    hexToAnsi256: {
      value: (hex) => styles3.rgbToAnsi256(...styles3.hexToRgb(hex)),
      enumerable: false
    },
    ansi256ToAnsi: {
      value(code) {
        if (code < 8) {
          return 30 + code;
        }
        if (code < 16) {
          return 90 + (code - 8);
        }
        let red;
        let green;
        let blue;
        if (code >= 232) {
          red = ((code - 232) * 10 + 8) / 255;
          green = red;
          blue = red;
        } else {
          code -= 16;
          const remainder = code % 36;
          red = Math.floor(code / 36) / 5;
          green = Math.floor(remainder / 6) / 5;
          blue = remainder % 6 / 5;
        }
        const value = Math.max(red, green, blue) * 2;
        if (value === 0) {
          return 30;
        }
        let result2 = 30 + (Math.round(blue) << 2 | Math.round(green) << 1 | Math.round(red));
        if (value === 2) {
          result2 += 60;
        }
        return result2;
      },
      enumerable: false
    },
    rgbToAnsi: {
      value: (red, green, blue) => styles3.ansi256ToAnsi(styles3.rgbToAnsi256(red, green, blue)),
      enumerable: false
    },
    hexToAnsi: {
      value: (hex) => styles3.ansi256ToAnsi(styles3.hexToAnsi256(hex)),
      enumerable: false
    }
  });
  return styles3;
}
var ansiStyles2 = assembleStyles2();
var ansi_styles_default2 = ansiStyles2;

// node_modules/chalk/source/vendor/supports-color/index.js
import process4 from "node:process";
import os2 from "node:os";
import tty from "node:tty";
function hasFlag(flag, argv = globalThis.Deno ? globalThis.Deno.args : process4.argv) {
  const prefix = flag.startsWith("-") ? "" : flag.length === 1 ? "-" : "--";
  const position = argv.indexOf(prefix + flag);
  const terminatorPosition = argv.indexOf("--");
  return position !== -1 && (terminatorPosition === -1 || position < terminatorPosition);
}
var { env: env2 } = process4;
var flagForceColor;
if (hasFlag("no-color") || hasFlag("no-colors") || hasFlag("color=false") || hasFlag("color=never")) {
  flagForceColor = 0;
} else if (hasFlag("color") || hasFlag("colors") || hasFlag("color=true") || hasFlag("color=always")) {
  flagForceColor = 1;
}
function envForceColor() {
  if ("FORCE_COLOR" in env2) {
    if (env2.FORCE_COLOR === "true") {
      return 1;
    }
    if (env2.FORCE_COLOR === "false") {
      return 0;
    }
    return env2.FORCE_COLOR.length === 0 ? 1 : Math.min(Number.parseInt(env2.FORCE_COLOR, 10), 3);
  }
}
function translateLevel(level) {
  if (level === 0) {
    return false;
  }
  return {
    level,
    hasBasic: true,
    has256: level >= 2,
    has16m: level >= 3
  };
}
function _supportsColor(haveStream, { streamIsTTY, sniffFlags = true } = {}) {
  const noFlagForceColor = envForceColor();
  if (noFlagForceColor !== undefined) {
    flagForceColor = noFlagForceColor;
  }
  const forceColor = sniffFlags ? flagForceColor : noFlagForceColor;
  if (forceColor === 0) {
    return 0;
  }
  if (sniffFlags) {
    if (hasFlag("color=16m") || hasFlag("color=full") || hasFlag("color=truecolor")) {
      return 3;
    }
    if (hasFlag("color=256")) {
      return 2;
    }
  }
  if ("TF_BUILD" in env2 && "AGENT_NAME" in env2) {
    return 1;
  }
  if (haveStream && !streamIsTTY && forceColor === undefined) {
    return 0;
  }
  const min2 = forceColor || 0;
  if (env2.TERM === "dumb") {
    return min2;
  }
  if (process4.platform === "win32") {
    const osRelease = os2.release().split(".");
    if (Number(osRelease[0]) >= 10 && Number(osRelease[2]) >= 10586) {
      return Number(osRelease[2]) >= 14931 ? 3 : 2;
    }
    return 1;
  }
  if ("CI" in env2) {
    if (["GITHUB_ACTIONS", "GITEA_ACTIONS", "CIRCLECI"].some((key) => (key in env2))) {
      return 3;
    }
    if (["TRAVIS", "APPVEYOR", "GITLAB_CI", "BUILDKITE", "DRONE"].some((sign) => (sign in env2)) || env2.CI_NAME === "codeship") {
      return 1;
    }
    return min2;
  }
  if ("TEAMCITY_VERSION" in env2) {
    return /^(9\.(0*[1-9]\d*)\.|\d{2,}\.)/.test(env2.TEAMCITY_VERSION) ? 1 : 0;
  }
  if (env2.COLORTERM === "truecolor") {
    return 3;
  }
  if (env2.TERM === "xterm-kitty") {
    return 3;
  }
  if (env2.TERM === "xterm-ghostty") {
    return 3;
  }
  if (env2.TERM === "wezterm") {
    return 3;
  }
  if ("TERM_PROGRAM" in env2) {
    const version = Number.parseInt((env2.TERM_PROGRAM_VERSION || "").split(".")[0], 10);
    switch (env2.TERM_PROGRAM) {
      case "iTerm.app": {
        return version >= 3 ? 3 : 2;
      }
      case "Apple_Terminal": {
        return 2;
      }
    }
  }
  if (/-256(color)?$/i.test(env2.TERM)) {
    return 2;
  }
  if (/^screen|^xterm|^vt100|^vt220|^rxvt|color|ansi|cygwin|linux/i.test(env2.TERM)) {
    return 1;
  }
  if ("COLORTERM" in env2) {
    return 1;
  }
  return min2;
}
function createSupportsColor(stream, options = {}) {
  const level = _supportsColor(stream, {
    streamIsTTY: stream && stream.isTTY,
    ...options
  });
  return translateLevel(level);
}
var supportsColor = {
  stdout: createSupportsColor({ isTTY: tty.isatty(1) }),
  stderr: createSupportsColor({ isTTY: tty.isatty(2) })
};
var supports_color_default = supportsColor;

// node_modules/chalk/source/utilities.js
function stringReplaceAll(string, substring, replacer) {
  let index = string.indexOf(substring);
  if (index === -1) {
    return string;
  }
  const substringLength = substring.length;
  let endIndex = 0;
  let returnValue = "";
  do {
    returnValue += string.slice(endIndex, index) + substring + replacer;
    endIndex = index + substringLength;
    index = string.indexOf(substring, endIndex);
  } while (index !== -1);
  returnValue += string.slice(endIndex);
  return returnValue;
}
function stringEncaseCRLFWithFirstIndex(string, prefix, postfix, index) {
  let endIndex = 0;
  let returnValue = "";
  do {
    const gotCR = string[index - 1] === "\r";
    returnValue += string.slice(endIndex, gotCR ? index - 1 : index) + prefix + (gotCR ? `\r
` : `
`) + postfix;
    endIndex = index + 1;
    index = string.indexOf(`
`, endIndex);
  } while (index !== -1);
  returnValue += string.slice(endIndex);
  return returnValue;
}

// node_modules/chalk/source/index.js
var { stdout: stdoutColor, stderr: stderrColor } = supports_color_default;
var GENERATOR = Symbol("GENERATOR");
var STYLER = Symbol("STYLER");
var IS_EMPTY = Symbol("IS_EMPTY");
var levelMapping = [
  "ansi",
  "ansi",
  "ansi256",
  "ansi16m"
];
var styles4 = Object.create(null);
var applyOptions = (object, options = {}) => {
  if (options.level && !(Number.isInteger(options.level) && options.level >= 0 && options.level <= 3)) {
    throw new Error("The `level` option should be an integer from 0 to 3");
  }
  const colorLevel = stdoutColor ? stdoutColor.level : 0;
  object.level = options.level === undefined ? colorLevel : options.level;
};
var chalkFactory = (options) => {
  const chalk = (...strings) => strings.join(" ");
  applyOptions(chalk, options);
  Object.setPrototypeOf(chalk, createChalk.prototype);
  return chalk;
};
function createChalk(options) {
  return chalkFactory(options);
}
Object.setPrototypeOf(createChalk.prototype, Function.prototype);
for (const [styleName, style] of Object.entries(ansi_styles_default2)) {
  styles4[styleName] = {
    get() {
      const builder = createBuilder(this, createStyler(style.open, style.close, this[STYLER]), this[IS_EMPTY]);
      Object.defineProperty(this, styleName, { value: builder });
      return builder;
    }
  };
}
styles4.visible = {
  get() {
    const builder = createBuilder(this, this[STYLER], true);
    Object.defineProperty(this, "visible", { value: builder });
    return builder;
  }
};
var getModelAnsi = (model, level, type, ...arguments_) => {
  if (model === "rgb") {
    if (level === "ansi16m") {
      return ansi_styles_default2[type].ansi16m(...arguments_);
    }
    if (level === "ansi256") {
      return ansi_styles_default2[type].ansi256(ansi_styles_default2.rgbToAnsi256(...arguments_));
    }
    return ansi_styles_default2[type].ansi(ansi_styles_default2.rgbToAnsi(...arguments_));
  }
  if (model === "hex") {
    return getModelAnsi("rgb", level, type, ...ansi_styles_default2.hexToRgb(...arguments_));
  }
  return ansi_styles_default2[type][model](...arguments_);
};
var usedModels = ["rgb", "hex", "ansi256"];
for (const model of usedModels) {
  styles4[model] = {
    get() {
      const { level } = this;
      return function(...arguments_) {
        const styler = createStyler(getModelAnsi(model, levelMapping[level], "color", ...arguments_), ansi_styles_default2.color.close, this[STYLER]);
        return createBuilder(this, styler, this[IS_EMPTY]);
      };
    }
  };
  const bgModel = "bg" + model[0].toUpperCase() + model.slice(1);
  styles4[bgModel] = {
    get() {
      const { level } = this;
      return function(...arguments_) {
        const styler = createStyler(getModelAnsi(model, levelMapping[level], "bgColor", ...arguments_), ansi_styles_default2.bgColor.close, this[STYLER]);
        return createBuilder(this, styler, this[IS_EMPTY]);
      };
    }
  };
}
var proto = Object.defineProperties(() => {}, {
  ...styles4,
  level: {
    enumerable: true,
    get() {
      return this[GENERATOR].level;
    },
    set(level) {
      this[GENERATOR].level = level;
    }
  }
});
var createStyler = (open, close, parent) => {
  let openAll;
  let closeAll;
  if (parent === undefined) {
    openAll = open;
    closeAll = close;
  } else {
    openAll = parent.openAll + open;
    closeAll = close + parent.closeAll;
  }
  return {
    open,
    close,
    openAll,
    closeAll,
    parent
  };
};
var createBuilder = (self, _styler, _isEmpty) => {
  const builder = (...arguments_) => applyStyle(builder, arguments_.length === 1 ? "" + arguments_[0] : arguments_.join(" "));
  Object.setPrototypeOf(builder, proto);
  builder[GENERATOR] = self;
  builder[STYLER] = _styler;
  builder[IS_EMPTY] = _isEmpty;
  return builder;
};
var applyStyle = (self, string) => {
  if (self.level <= 0 || !string) {
    return self[IS_EMPTY] ? "" : string;
  }
  let styler = self[STYLER];
  if (styler === undefined) {
    return string;
  }
  const { openAll, closeAll } = styler;
  if (string.includes("\x1B")) {
    while (styler !== undefined) {
      string = stringReplaceAll(string, styler.close, styler.open);
      styler = styler.parent;
    }
  }
  const lfIndex = string.indexOf(`
`);
  if (lfIndex !== -1) {
    string = stringEncaseCRLFWithFirstIndex(string, closeAll, openAll, lfIndex);
  }
  return openAll + string + closeAll;
};
Object.defineProperties(createChalk.prototype, styles4);
var chalk = createChalk();
var chalkStderr = createChalk({ level: stderrColor ? stderrColor.level : 0 });
var source_default = chalk;

// node_modules/ink/build/colorize.js
var rgbRegex = /^rgb\(\s?(\d+),\s?(\d+),\s?(\d+)\s?\)$/;
var ansiRegex2 = /^ansi256\(\s?(\d+)\s?\)$/;
var isNamedColor = (color) => {
  return color in source_default;
};
var colorize = (str, color, type) => {
  if (!color) {
    return str;
  }
  if (isNamedColor(color)) {
    if (type === "foreground") {
      return source_default[color](str);
    }
    const methodName = `bg${color[0].toUpperCase() + color.slice(1)}`;
    return source_default[methodName](str);
  }
  if (color.startsWith("#")) {
    return type === "foreground" ? source_default.hex(color)(str) : source_default.bgHex(color)(str);
  }
  if (color.startsWith("ansi256")) {
    const matches2 = ansiRegex2.exec(color);
    if (!matches2) {
      return str;
    }
    const value = Number(matches2[1]);
    return type === "foreground" ? source_default.ansi256(value)(str) : source_default.bgAnsi256(value)(str);
  }
  if (color.startsWith("rgb")) {
    const matches2 = rgbRegex.exec(color);
    if (!matches2) {
      return str;
    }
    const firstValue = Number(matches2[1]);
    const secondValue = Number(matches2[2]);
    const thirdValue = Number(matches2[3]);
    return type === "foreground" ? source_default.rgb(firstValue, secondValue, thirdValue)(str) : source_default.bgRgb(firstValue, secondValue, thirdValue)(str);
  }
  return str;
};
var colorize_default = colorize;

// node_modules/ink/build/render-border.js
var renderBorder = (x, y, node, output) => {
  if (node.style.borderStyle) {
    const width = node.yogaNode.getComputedWidth();
    const height = node.yogaNode.getComputedHeight();
    const box = typeof node.style.borderStyle === "string" ? import_cli_boxes.default[node.style.borderStyle] : node.style.borderStyle;
    const topBorderColor = node.style.borderTopColor ?? node.style.borderColor;
    const bottomBorderColor = node.style.borderBottomColor ?? node.style.borderColor;
    const leftBorderColor = node.style.borderLeftColor ?? node.style.borderColor;
    const rightBorderColor = node.style.borderRightColor ?? node.style.borderColor;
    const dimTopBorderColor = node.style.borderTopDimColor ?? node.style.borderDimColor;
    const dimBottomBorderColor = node.style.borderBottomDimColor ?? node.style.borderDimColor;
    const dimLeftBorderColor = node.style.borderLeftDimColor ?? node.style.borderDimColor;
    const dimRightBorderColor = node.style.borderRightDimColor ?? node.style.borderDimColor;
    const showTopBorder = node.style.borderTop !== false;
    const showBottomBorder = node.style.borderBottom !== false;
    const showLeftBorder = node.style.borderLeft !== false;
    const showRightBorder = node.style.borderRight !== false;
    const contentWidth = width - (showLeftBorder ? 1 : 0) - (showRightBorder ? 1 : 0);
    let topBorder = showTopBorder ? colorize_default((showLeftBorder ? box.topLeft : "") + box.top.repeat(contentWidth) + (showRightBorder ? box.topRight : ""), topBorderColor, "foreground") : undefined;
    if (showTopBorder && dimTopBorderColor) {
      topBorder = source_default.dim(topBorder);
    }
    let verticalBorderHeight = height;
    if (showTopBorder) {
      verticalBorderHeight -= 1;
    }
    if (showBottomBorder) {
      verticalBorderHeight -= 1;
    }
    let leftBorder = (colorize_default(box.left, leftBorderColor, "foreground") + `
`).repeat(verticalBorderHeight);
    if (dimLeftBorderColor) {
      leftBorder = source_default.dim(leftBorder);
    }
    let rightBorder = (colorize_default(box.right, rightBorderColor, "foreground") + `
`).repeat(verticalBorderHeight);
    if (dimRightBorderColor) {
      rightBorder = source_default.dim(rightBorder);
    }
    let bottomBorder = showBottomBorder ? colorize_default((showLeftBorder ? box.bottomLeft : "") + box.bottom.repeat(contentWidth) + (showRightBorder ? box.bottomRight : ""), bottomBorderColor, "foreground") : undefined;
    if (showBottomBorder && dimBottomBorderColor) {
      bottomBorder = source_default.dim(bottomBorder);
    }
    const offsetY = showTopBorder ? 1 : 0;
    if (topBorder) {
      output.write(x, y, topBorder, { transformers: [] });
    }
    if (showLeftBorder) {
      output.write(x, y + offsetY, leftBorder, { transformers: [] });
    }
    if (showRightBorder) {
      output.write(x + width - 1, y + offsetY, rightBorder, {
        transformers: []
      });
    }
    if (bottomBorder) {
      output.write(x, y + height - 1, bottomBorder, { transformers: [] });
    }
  }
};
var render_border_default = renderBorder;

// node_modules/ink/build/render-node-to-output.js
var applyPaddingToText = (node, text) => {
  const yogaNode = node.childNodes[0]?.yogaNode;
  if (yogaNode) {
    const offsetX = yogaNode.getComputedLeft();
    const offsetY = yogaNode.getComputedTop();
    text = `
`.repeat(offsetY) + indentString(text, offsetX);
  }
  return text;
};
var renderNodeToOutput = (node, output, options) => {
  const { offsetX = 0, offsetY = 0, transformers = [], skipStaticElements } = options;
  if (skipStaticElements && node.internal_static) {
    return;
  }
  const { yogaNode } = node;
  if (yogaNode) {
    if (yogaNode.getDisplay() === src_default.DISPLAY_NONE) {
      return;
    }
    const x = offsetX + yogaNode.getComputedLeft();
    const y = offsetY + yogaNode.getComputedTop();
    let newTransformers = transformers;
    if (typeof node.internal_transform === "function") {
      newTransformers = [node.internal_transform, ...transformers];
    }
    if (node.nodeName === "ink-text") {
      let text = squash_text_nodes_default(node);
      if (text.length > 0) {
        const currentWidth = widestLine(text);
        const maxWidth = get_max_width_default(yogaNode);
        if (currentWidth > maxWidth) {
          const textWrap = node.style.textWrap ?? "wrap";
          text = wrap_text_default(text, maxWidth, textWrap);
        }
        text = applyPaddingToText(node, text);
        output.write(x, y, text, { transformers: newTransformers });
      }
      return;
    }
    let clipped = false;
    if (node.nodeName === "ink-box") {
      render_border_default(x, y, node, output);
      const clipHorizontally = node.style.overflowX === "hidden" || node.style.overflow === "hidden";
      const clipVertically = node.style.overflowY === "hidden" || node.style.overflow === "hidden";
      if (clipHorizontally || clipVertically) {
        const x1 = clipHorizontally ? x + yogaNode.getComputedBorder(src_default.EDGE_LEFT) : undefined;
        const x2 = clipHorizontally ? x + yogaNode.getComputedWidth() - yogaNode.getComputedBorder(src_default.EDGE_RIGHT) : undefined;
        const y1 = clipVertically ? y + yogaNode.getComputedBorder(src_default.EDGE_TOP) : undefined;
        const y2 = clipVertically ? y + yogaNode.getComputedHeight() - yogaNode.getComputedBorder(src_default.EDGE_BOTTOM) : undefined;
        output.clip({ x1, x2, y1, y2 });
        clipped = true;
      }
    }
    if (node.nodeName === "ink-root" || node.nodeName === "ink-box") {
      for (const childNode of node.childNodes) {
        renderNodeToOutput(childNode, output, {
          offsetX: x,
          offsetY: y,
          transformers: newTransformers,
          skipStaticElements
        });
      }
      if (clipped) {
        output.unclip();
      }
    }
  }
};
var render_node_to_output_default = renderNodeToOutput;

// node_modules/slice-ansi/node_modules/is-fullwidth-code-point/index.js
function isFullwidthCodePoint2(codePoint) {
  if (!Number.isInteger(codePoint)) {
    return false;
  }
  return isFullWidth(codePoint) || isWide(codePoint);
}

// node_modules/slice-ansi/index.js
var ESCAPES3 = new Set([27, 155]);
var CODE_POINT_0 = "0".codePointAt(0);
var CODE_POINT_9 = "9".codePointAt(0);
var MAX_ANSI_SEQUENCE_LENGTH = 19;
var endCodesSet = new Set;
var endCodesMap = new Map;
for (const [start, end] of ansi_styles_default.codes) {
  endCodesSet.add(ansi_styles_default.color.ansi(end));
  endCodesMap.set(ansi_styles_default.color.ansi(start), ansi_styles_default.color.ansi(end));
}
function getEndCode(code) {
  if (endCodesSet.has(code)) {
    return code;
  }
  if (endCodesMap.has(code)) {
    return endCodesMap.get(code);
  }
  code = code.slice(2);
  if (code.includes(";")) {
    code = code[0] + "0";
  }
  const returnValue = ansi_styles_default.codes.get(Number.parseInt(code, 10));
  if (returnValue) {
    return ansi_styles_default.color.ansi(returnValue);
  }
  return ansi_styles_default.reset.open;
}
function findNumberIndex(string) {
  for (let index = 0;index < string.length; index++) {
    const codePoint = string.codePointAt(index);
    if (codePoint >= CODE_POINT_0 && codePoint <= CODE_POINT_9) {
      return index;
    }
  }
  return -1;
}
function parseAnsiCode(string, offset) {
  string = string.slice(offset, offset + MAX_ANSI_SEQUENCE_LENGTH);
  const startIndex = findNumberIndex(string);
  if (startIndex !== -1) {
    let endIndex = string.indexOf("m", startIndex);
    if (endIndex === -1) {
      endIndex = string.length;
    }
    return string.slice(0, endIndex + 1);
  }
}
function tokenize(string, endCharacter = Number.POSITIVE_INFINITY) {
  const returnValue = [];
  let index = 0;
  let visibleCount = 0;
  while (index < string.length) {
    const codePoint = string.codePointAt(index);
    if (ESCAPES3.has(codePoint)) {
      const code = parseAnsiCode(string, index);
      if (code) {
        returnValue.push({
          type: "ansi",
          code,
          endCode: getEndCode(code)
        });
        index += code.length;
        continue;
      }
    }
    const isFullWidth2 = isFullwidthCodePoint2(codePoint);
    const character = String.fromCodePoint(codePoint);
    returnValue.push({
      type: "character",
      value: character,
      isFullWidth: isFullWidth2
    });
    index += character.length;
    visibleCount += isFullWidth2 ? 2 : character.length;
    if (visibleCount >= endCharacter) {
      break;
    }
  }
  return returnValue;
}
function reduceAnsiCodes(codes) {
  let returnValue = [];
  for (const code of codes) {
    if (code.code === ansi_styles_default.reset.open) {
      returnValue = [];
    } else if (endCodesSet.has(code.code)) {
      returnValue = returnValue.filter((returnValueCode) => returnValueCode.endCode !== code.code);
    } else {
      returnValue = returnValue.filter((returnValueCode) => returnValueCode.endCode !== code.endCode);
      returnValue.push(code);
    }
  }
  return returnValue;
}
function undoAnsiCodes(codes) {
  const reduced = reduceAnsiCodes(codes);
  const endCodes = reduced.map(({ endCode }) => endCode);
  return endCodes.reverse().join("");
}
function sliceAnsi2(string, start, end) {
  const tokens = tokenize(string, end);
  let activeCodes = [];
  let position = 0;
  let returnValue = "";
  let include = false;
  for (const token of tokens) {
    if (end !== undefined && position >= end) {
      break;
    }
    if (token.type === "ansi") {
      activeCodes.push(token);
      if (include) {
        returnValue += token.code;
      }
    } else {
      if (!include && position >= start) {
        include = true;
        activeCodes = reduceAnsiCodes(activeCodes);
        returnValue = activeCodes.map(({ code }) => code).join("");
      }
      if (include) {
        returnValue += token.value;
      }
      position += token.isFullWidth ? 2 : token.value.length;
    }
  }
  returnValue += undoAnsiCodes(activeCodes);
  return returnValue;
}

// node_modules/@alcalzone/ansi-tokenize/build/ansiCodes.js
var ESCAPES4 = new Set([27, 155]);
var endCodesSet2 = new Set;
var endCodesMap2 = new Map;
for (const [start, end] of ansi_styles_default.codes) {
  endCodesSet2.add(ansi_styles_default.color.ansi(end));
  endCodesMap2.set(ansi_styles_default.color.ansi(start), ansi_styles_default.color.ansi(end));
}
var linkStartCodePrefix = "\x1B]8;;";
var linkStartCodePrefixCharCodes = linkStartCodePrefix.split("").map((char) => char.charCodeAt(0));
var linkCodeSuffix = "\x07";
var linkCodeSuffixCharCode = linkCodeSuffix.charCodeAt(0);
var linkEndCode = `\x1B]8;;${linkCodeSuffix}`;
function getEndCode2(code) {
  if (endCodesSet2.has(code))
    return code;
  if (endCodesMap2.has(code))
    return endCodesMap2.get(code);
  if (code.startsWith(linkStartCodePrefix))
    return linkEndCode;
  code = code.slice(2);
  if (code.includes(";")) {
    code = code[0] + "0";
  }
  const ret = ansi_styles_default.codes.get(parseInt(code, 10));
  if (ret) {
    return ansi_styles_default.color.ansi(ret);
  } else {
    return ansi_styles_default.reset.open;
  }
}
function ansiCodesToString(codes) {
  return codes.map((code) => code.code).join("");
}
// node_modules/@alcalzone/ansi-tokenize/build/reduce.js
function reduceAnsiCodes2(codes) {
  return reduceAnsiCodesIncremental([], codes);
}
function reduceAnsiCodesIncremental(codes, newCodes) {
  let ret = [...codes];
  for (const code of newCodes) {
    if (code.code === ansi_styles_default.reset.open) {
      ret = [];
    } else if (endCodesSet2.has(code.code)) {
      ret = ret.filter((retCode) => retCode.endCode !== code.code);
    } else {
      ret = ret.filter((retCode) => retCode.endCode !== code.endCode);
      ret.push(code);
    }
  }
  return ret;
}

// node_modules/@alcalzone/ansi-tokenize/build/undo.js
function undoAnsiCodes2(codes) {
  return reduceAnsiCodes2(codes).reverse().map((code) => ({
    ...code,
    code: code.endCode
  }));
}

// node_modules/@alcalzone/ansi-tokenize/build/diff.js
function diffAnsiCodes(from, to) {
  const endCodesInTo = new Set(to.map((code) => code.endCode));
  const startCodesInFrom = new Set(from.map((code) => code.code));
  return [
    ...undoAnsiCodes2(from.filter((code) => !endCodesInTo.has(code.endCode))),
    ...to.filter((code) => !startCodesInFrom.has(code.code))
  ];
}
// node_modules/@alcalzone/ansi-tokenize/build/styledChars.js
function styledCharsFromTokens(tokens) {
  let codes = [];
  const ret = [];
  for (const token of tokens) {
    if (token.type === "ansi") {
      codes = reduceAnsiCodesIncremental(codes, [token]);
    } else if (token.type === "char") {
      ret.push({
        ...token,
        styles: [...codes]
      });
    }
  }
  return ret;
}
function styledCharsToString(chars) {
  let ret = "";
  for (let i = 0;i < chars.length; i++) {
    const char = chars[i];
    if (i === 0) {
      ret += ansiCodesToString(char.styles);
    } else {
      ret += ansiCodesToString(diffAnsiCodes(chars[i - 1].styles, char.styles));
    }
    ret += char.value;
    if (i === chars.length - 1) {
      ret += ansiCodesToString(diffAnsiCodes(char.styles, []));
    }
  }
  return ret;
}
// node_modules/@alcalzone/ansi-tokenize/build/tokenize.js
function findNumberIndex2(str) {
  for (let index = 0;index < str.length; index++) {
    const charCode = str.charCodeAt(index);
    if (charCode >= 48 && charCode <= 57) {
      return index;
    }
  }
  return -1;
}
function parseLinkCode(string, offset) {
  string = string.slice(offset);
  for (let index = 1;index < linkStartCodePrefixCharCodes.length; index++) {
    if (string.charCodeAt(index) !== linkStartCodePrefixCharCodes[index]) {
      return;
    }
  }
  const endIndex = string.indexOf("\x07", linkStartCodePrefix.length);
  if (endIndex === -1)
    return;
  return string.slice(0, endIndex + 1);
}
function parseAnsiCode2(string, offset) {
  string = string.slice(offset, offset + 19);
  const startIndex = findNumberIndex2(string);
  if (startIndex !== -1) {
    let endIndex = string.indexOf("m", startIndex);
    if (endIndex === -1) {
      endIndex = string.length;
    }
    return string.slice(0, endIndex + 1);
  }
}
function tokenize2(str, endChar = Number.POSITIVE_INFINITY) {
  const ret = [];
  let index = 0;
  let visible = 0;
  while (index < str.length) {
    const codePoint = str.codePointAt(index);
    if (ESCAPES4.has(codePoint)) {
      const code = parseLinkCode(str, index) || parseAnsiCode2(str, index);
      if (code) {
        ret.push({
          type: "ansi",
          code,
          endCode: getEndCode2(code)
        });
        index += code.length;
        continue;
      }
    }
    const fullWidth = isFullwidthCodePoint(codePoint);
    const character = String.fromCodePoint(codePoint);
    ret.push({
      type: "char",
      value: character,
      fullWidth
    });
    index += character.length;
    visible += fullWidth ? 2 : character.length;
    if (visible >= endChar) {
      break;
    }
  }
  return ret;
}
// node_modules/ink/build/output.js
class Output {
  width;
  height;
  operations = [];
  constructor(options) {
    const { width, height } = options;
    this.width = width;
    this.height = height;
  }
  write(x, y, text, options) {
    const { transformers } = options;
    if (!text) {
      return;
    }
    this.operations.push({
      type: "write",
      x,
      y,
      text,
      transformers
    });
  }
  clip(clip) {
    this.operations.push({
      type: "clip",
      clip
    });
  }
  unclip() {
    this.operations.push({
      type: "unclip"
    });
  }
  get() {
    const output = [];
    for (let y = 0;y < this.height; y++) {
      const row = [];
      for (let x = 0;x < this.width; x++) {
        row.push({
          type: "char",
          value: " ",
          fullWidth: false,
          styles: []
        });
      }
      output.push(row);
    }
    const clips = [];
    for (const operation of this.operations) {
      if (operation.type === "clip") {
        clips.push(operation.clip);
      }
      if (operation.type === "unclip") {
        clips.pop();
      }
      if (operation.type === "write") {
        const { text, transformers } = operation;
        let { x, y } = operation;
        let lines = text.split(`
`);
        const clip = clips.at(-1);
        if (clip) {
          const clipHorizontally = typeof clip?.x1 === "number" && typeof clip?.x2 === "number";
          const clipVertically = typeof clip?.y1 === "number" && typeof clip?.y2 === "number";
          if (clipHorizontally) {
            const width = widestLine(text);
            if (x + width < clip.x1 || x > clip.x2) {
              continue;
            }
          }
          if (clipVertically) {
            const height = lines.length;
            if (y + height < clip.y1 || y > clip.y2) {
              continue;
            }
          }
          if (clipHorizontally) {
            lines = lines.map((line) => {
              const from = x < clip.x1 ? clip.x1 - x : 0;
              const width = stringWidth(line);
              const to = x + width > clip.x2 ? clip.x2 - x : width;
              return sliceAnsi2(line, from, to);
            });
            if (x < clip.x1) {
              x = clip.x1;
            }
          }
          if (clipVertically) {
            const from = y < clip.y1 ? clip.y1 - y : 0;
            const height = lines.length;
            const to = y + height > clip.y2 ? clip.y2 - y : height;
            lines = lines.slice(from, to);
            if (y < clip.y1) {
              y = clip.y1;
            }
          }
        }
        let offsetY = 0;
        for (let [index, line] of lines.entries()) {
          const currentLine = output[y + offsetY];
          if (!currentLine) {
            continue;
          }
          for (const transformer of transformers) {
            line = transformer(line, index);
          }
          const characters = styledCharsFromTokens(tokenize2(line));
          let offsetX = x;
          for (const character of characters) {
            currentLine[offsetX] = character;
            const isWideCharacter = character.fullWidth || character.value.length > 1;
            if (isWideCharacter) {
              currentLine[offsetX + 1] = {
                type: "char",
                value: "",
                fullWidth: false,
                styles: character.styles
              };
            }
            offsetX += isWideCharacter ? 2 : 1;
          }
          offsetY++;
        }
      }
    }
    const generatedOutput = output.map((line) => {
      const lineWithoutEmptyItems = line.filter((item) => item !== undefined);
      return styledCharsToString(lineWithoutEmptyItems).trimEnd();
    }).join(`
`);
    return {
      output: generatedOutput,
      height: output.length
    };
  }
}

// node_modules/ink/build/renderer.js
var renderer = (node) => {
  if (node.yogaNode) {
    const output = new Output({
      width: node.yogaNode.getComputedWidth(),
      height: node.yogaNode.getComputedHeight()
    });
    render_node_to_output_default(node, output, { skipStaticElements: true });
    let staticOutput;
    if (node.staticNode?.yogaNode) {
      staticOutput = new Output({
        width: node.staticNode.yogaNode.getComputedWidth(),
        height: node.staticNode.yogaNode.getComputedHeight()
      });
      render_node_to_output_default(node.staticNode, staticOutput, {
        skipStaticElements: false
      });
    }
    const { output: generatedOutput, height: outputHeight } = output.get();
    return {
      output: generatedOutput,
      outputHeight,
      staticOutput: staticOutput ? `${staticOutput.get().output}
` : ""
    };
  }
  return {
    output: "",
    outputHeight: 0,
    staticOutput: ""
  };
};
var renderer_default = renderer;

// node_modules/cli-cursor/index.js
import process6 from "node:process";

// node_modules/restore-cursor/index.js
var import_onetime = __toESM(require_onetime(), 1);
var import_signal_exit = __toESM(require_signal_exit(), 1);
import process5 from "node:process";
var restoreCursor = import_onetime.default(() => {
  import_signal_exit.default(() => {
    process5.stderr.write("\x1B[?25h");
  }, { alwaysLast: true });
});
var restore_cursor_default = restoreCursor;

// node_modules/cli-cursor/index.js
var isHidden = false;
var cliCursor = {};
cliCursor.show = (writableStream = process6.stderr) => {
  if (!writableStream.isTTY) {
    return;
  }
  isHidden = false;
  writableStream.write("\x1B[?25h");
};
cliCursor.hide = (writableStream = process6.stderr) => {
  if (!writableStream.isTTY) {
    return;
  }
  restore_cursor_default();
  isHidden = true;
  writableStream.write("\x1B[?25l");
};
cliCursor.toggle = (force, writableStream) => {
  if (force !== undefined) {
    isHidden = force;
  }
  if (isHidden) {
    cliCursor.show(writableStream);
  } else {
    cliCursor.hide(writableStream);
  }
};
var cli_cursor_default = cliCursor;

// node_modules/ink/build/log-update.js
var create2 = (stream, { showCursor = false } = {}) => {
  let previousLineCount = 0;
  let previousOutput = "";
  let hasHiddenCursor = false;
  const render = (str) => {
    if (!showCursor && !hasHiddenCursor) {
      cli_cursor_default.hide();
      hasHiddenCursor = true;
    }
    const output = str + `
`;
    if (output === previousOutput) {
      return;
    }
    previousOutput = output;
    stream.write(exports_base.eraseLines(previousLineCount) + output);
    previousLineCount = output.split(`
`).length;
  };
  render.clear = () => {
    stream.write(exports_base.eraseLines(previousLineCount));
    previousOutput = "";
    previousLineCount = 0;
  };
  render.done = () => {
    previousOutput = "";
    previousLineCount = 0;
    if (!showCursor) {
      cli_cursor_default.show();
      hasHiddenCursor = false;
    }
  };
  return render;
};
var logUpdate = { create: create2 };
var log_update_default = logUpdate;

// node_modules/ink/build/instances.js
var instances = new WeakMap;
var instances_default = instances;

// node_modules/ink/build/components/App.js
var import_react9 = __toESM(require_react(), 1);
import { EventEmitter as EventEmitter2 } from "node:events";
import process10 from "node:process";

// node_modules/ink/build/components/AppContext.js
var import_react = __toESM(require_react(), 1);
var AppContext = import_react.createContext({
  exit() {}
});
AppContext.displayName = "InternalAppContext";
var AppContext_default = AppContext;

// node_modules/ink/build/components/StdinContext.js
var import_react2 = __toESM(require_react(), 1);
import { EventEmitter } from "node:events";
import process7 from "node:process";
var StdinContext = import_react2.createContext({
  stdin: process7.stdin,
  internal_eventEmitter: new EventEmitter,
  setRawMode() {},
  isRawModeSupported: false,
  internal_exitOnCtrlC: true
});
StdinContext.displayName = "InternalStdinContext";
var StdinContext_default = StdinContext;

// node_modules/ink/build/components/StdoutContext.js
var import_react3 = __toESM(require_react(), 1);
import process8 from "node:process";
var StdoutContext = import_react3.createContext({
  stdout: process8.stdout,
  write() {}
});
StdoutContext.displayName = "InternalStdoutContext";
var StdoutContext_default = StdoutContext;

// node_modules/ink/build/components/StderrContext.js
var import_react4 = __toESM(require_react(), 1);
import process9 from "node:process";
var StderrContext = import_react4.createContext({
  stderr: process9.stderr,
  write() {}
});
StderrContext.displayName = "InternalStderrContext";
var StderrContext_default = StderrContext;

// node_modules/ink/build/components/FocusContext.js
var import_react5 = __toESM(require_react(), 1);
var FocusContext = import_react5.createContext({
  activeId: undefined,
  add() {},
  remove() {},
  activate() {},
  deactivate() {},
  enableFocus() {},
  disableFocus() {},
  focusNext() {},
  focusPrevious() {},
  focus() {}
});
FocusContext.displayName = "InternalFocusContext";
var FocusContext_default = FocusContext;

// node_modules/ink/build/components/ErrorOverview.js
var import_react8 = __toESM(require_react(), 1);
var import_stack_utils = __toESM(require_stack_utils(), 1);
import * as fs from "node:fs";
import { cwd } from "node:process";

// node_modules/convert-to-spaces/dist/index.js
var convertToSpaces = (input, spaces = 2) => {
  return input.replace(/^\t+/gm, ($1) => " ".repeat($1.length * spaces));
};
var dist_default2 = convertToSpaces;

// node_modules/code-excerpt/dist/index.js
var generateLineNumbers = (line, around) => {
  const lineNumbers = [];
  const min2 = line - around;
  const max2 = line + around;
  for (let lineNumber = min2;lineNumber <= max2; lineNumber++) {
    lineNumbers.push(lineNumber);
  }
  return lineNumbers;
};
var codeExcerpt = (source, line, options = {}) => {
  var _a;
  if (typeof source !== "string") {
    throw new TypeError("Source code is missing.");
  }
  if (!line || line < 1) {
    throw new TypeError("Line number must start from `1`.");
  }
  const lines = dist_default2(source).split(/\r?\n/);
  if (line > lines.length) {
    return;
  }
  return generateLineNumbers(line, (_a = options.around) !== null && _a !== undefined ? _a : 3).filter((line2) => lines[line2 - 1] !== undefined).map((line2) => ({ line: line2, value: lines[line2 - 1] }));
};
var dist_default3 = codeExcerpt;

// node_modules/ink/build/components/Box.js
var import_react6 = __toESM(require_react(), 1);
var Box = import_react6.forwardRef(({ children, ...style }, ref) => {
  return import_react6.default.createElement("ink-box", { ref, style: {
    ...style,
    overflowX: style.overflowX ?? style.overflow ?? "visible",
    overflowY: style.overflowY ?? style.overflow ?? "visible"
  } }, children);
});
Box.displayName = "Box";
Box.defaultProps = {
  flexWrap: "nowrap",
  flexDirection: "row",
  flexGrow: 0,
  flexShrink: 1
};
var Box_default = Box;

// node_modules/ink/build/components/Text.js
var import_react7 = __toESM(require_react(), 1);
function Text({ color, backgroundColor, dimColor = false, bold = false, italic = false, underline = false, strikethrough = false, inverse = false, wrap: wrap2 = "wrap", children }) {
  if (children === undefined || children === null) {
    return null;
  }
  const transform2 = (children2) => {
    if (dimColor) {
      children2 = source_default.dim(children2);
    }
    if (color) {
      children2 = colorize_default(children2, color, "foreground");
    }
    if (backgroundColor) {
      children2 = colorize_default(children2, backgroundColor, "background");
    }
    if (bold) {
      children2 = source_default.bold(children2);
    }
    if (italic) {
      children2 = source_default.italic(children2);
    }
    if (underline) {
      children2 = source_default.underline(children2);
    }
    if (strikethrough) {
      children2 = source_default.strikethrough(children2);
    }
    if (inverse) {
      children2 = source_default.inverse(children2);
    }
    return children2;
  };
  return import_react7.default.createElement("ink-text", { style: { flexGrow: 0, flexShrink: 1, flexDirection: "row", textWrap: wrap2 }, internal_transform: transform2 }, children);
}

// node_modules/ink/build/components/ErrorOverview.js
var cleanupPath = (path) => {
  return path?.replace(`file://${cwd()}/`, "");
};
var stackUtils = new import_stack_utils.default({
  cwd: cwd(),
  internals: import_stack_utils.default.nodeInternals()
});
function ErrorOverview({ error }) {
  const stack = error.stack ? error.stack.split(`
`).slice(1) : undefined;
  const origin = stack ? stackUtils.parseLine(stack[0]) : undefined;
  const filePath = cleanupPath(origin?.file);
  let excerpt;
  let lineWidth = 0;
  if (filePath && origin?.line && fs.existsSync(filePath)) {
    const sourceCode = fs.readFileSync(filePath, "utf8");
    excerpt = dist_default3(sourceCode, origin.line);
    if (excerpt) {
      for (const { line } of excerpt) {
        lineWidth = Math.max(lineWidth, String(line).length);
      }
    }
  }
  return import_react8.default.createElement(Box_default, { flexDirection: "column", padding: 1 }, import_react8.default.createElement(Box_default, null, import_react8.default.createElement(Text, { backgroundColor: "red", color: "white" }, " ", "ERROR", " "), import_react8.default.createElement(Text, null, " ", error.message)), origin && filePath && import_react8.default.createElement(Box_default, { marginTop: 1 }, import_react8.default.createElement(Text, { dimColor: true }, filePath, ":", origin.line, ":", origin.column)), origin && excerpt && import_react8.default.createElement(Box_default, { marginTop: 1, flexDirection: "column" }, excerpt.map(({ line, value }) => import_react8.default.createElement(Box_default, { key: line }, import_react8.default.createElement(Box_default, { width: lineWidth + 1 }, import_react8.default.createElement(Text, { dimColor: line !== origin.line, backgroundColor: line === origin.line ? "red" : undefined, color: line === origin.line ? "white" : undefined }, String(line).padStart(lineWidth, " "), ":")), import_react8.default.createElement(Text, { key: line, backgroundColor: line === origin.line ? "red" : undefined, color: line === origin.line ? "white" : undefined }, " " + value)))), error.stack && import_react8.default.createElement(Box_default, { marginTop: 1, flexDirection: "column" }, error.stack.split(`
`).slice(1).map((line) => {
    const parsedLine = stackUtils.parseLine(line);
    if (!parsedLine) {
      return import_react8.default.createElement(Box_default, { key: line }, import_react8.default.createElement(Text, { dimColor: true }, "- "), import_react8.default.createElement(Text, { dimColor: true, bold: true }, line));
    }
    return import_react8.default.createElement(Box_default, { key: line }, import_react8.default.createElement(Text, { dimColor: true }, "- "), import_react8.default.createElement(Text, { dimColor: true, bold: true }, parsedLine.function), import_react8.default.createElement(Text, { dimColor: true, color: "gray" }, " ", "(", cleanupPath(parsedLine.file) ?? "", ":", parsedLine.line, ":", parsedLine.column, ")"));
  })));
}

// node_modules/ink/build/components/App.js
var tab = "\t";
var shiftTab = "\x1B[Z";
var escape2 = "\x1B";

class App extends import_react9.PureComponent {
  static displayName = "InternalApp";
  static getDerivedStateFromError(error) {
    return { error };
  }
  state = {
    isFocusEnabled: true,
    activeFocusId: undefined,
    focusables: [],
    error: undefined
  };
  rawModeEnabledCount = 0;
  internal_eventEmitter = new EventEmitter2;
  isRawModeSupported() {
    return this.props.stdin.isTTY;
  }
  render() {
    return import_react9.default.createElement(AppContext_default.Provider, {
      value: {
        exit: this.handleExit
      }
    }, import_react9.default.createElement(StdinContext_default.Provider, {
      value: {
        stdin: this.props.stdin,
        setRawMode: this.handleSetRawMode,
        isRawModeSupported: this.isRawModeSupported(),
        internal_exitOnCtrlC: this.props.exitOnCtrlC,
        internal_eventEmitter: this.internal_eventEmitter
      }
    }, import_react9.default.createElement(StdoutContext_default.Provider, {
      value: {
        stdout: this.props.stdout,
        write: this.props.writeToStdout
      }
    }, import_react9.default.createElement(StderrContext_default.Provider, {
      value: {
        stderr: this.props.stderr,
        write: this.props.writeToStderr
      }
    }, import_react9.default.createElement(FocusContext_default.Provider, {
      value: {
        activeId: this.state.activeFocusId,
        add: this.addFocusable,
        remove: this.removeFocusable,
        activate: this.activateFocusable,
        deactivate: this.deactivateFocusable,
        enableFocus: this.enableFocus,
        disableFocus: this.disableFocus,
        focusNext: this.focusNext,
        focusPrevious: this.focusPrevious,
        focus: this.focus
      }
    }, this.state.error ? import_react9.default.createElement(ErrorOverview, { error: this.state.error }) : this.props.children)))));
  }
  componentDidMount() {
    cli_cursor_default.hide(this.props.stdout);
  }
  componentWillUnmount() {
    cli_cursor_default.show(this.props.stdout);
    if (this.isRawModeSupported()) {
      this.handleSetRawMode(false);
    }
  }
  componentDidCatch(error) {
    this.handleExit(error);
  }
  handleSetRawMode = (isEnabled) => {
    const { stdin } = this.props;
    if (!this.isRawModeSupported()) {
      if (stdin === process10.stdin) {
        throw new Error(`Raw mode is not supported on the current process.stdin, which Ink uses as input stream by default.
Read about how to prevent this error on https://github.com/vadimdemedes/ink/#israwmodesupported`);
      } else {
        throw new Error(`Raw mode is not supported on the stdin provided to Ink.
Read about how to prevent this error on https://github.com/vadimdemedes/ink/#israwmodesupported`);
      }
    }
    stdin.setEncoding("utf8");
    if (isEnabled) {
      if (this.rawModeEnabledCount === 0) {
        stdin.ref();
        stdin.setRawMode(true);
        stdin.addListener("readable", this.handleReadable);
      }
      this.rawModeEnabledCount++;
      return;
    }
    if (--this.rawModeEnabledCount === 0) {
      stdin.setRawMode(false);
      stdin.removeListener("readable", this.handleReadable);
      stdin.unref();
    }
  };
  handleReadable = () => {
    let chunk2;
    while ((chunk2 = this.props.stdin.read()) !== null) {
      this.handleInput(chunk2);
      this.internal_eventEmitter.emit("input", chunk2);
    }
  };
  handleInput = (input) => {
    if (input === "\x03" && this.props.exitOnCtrlC) {
      this.handleExit();
    }
    if (input === escape2 && this.state.activeFocusId) {
      this.setState({
        activeFocusId: undefined
      });
    }
    if (this.state.isFocusEnabled && this.state.focusables.length > 0) {
      if (input === tab) {
        this.focusNext();
      }
      if (input === shiftTab) {
        this.focusPrevious();
      }
    }
  };
  handleExit = (error) => {
    if (this.isRawModeSupported()) {
      this.handleSetRawMode(false);
    }
    this.props.onExit(error);
  };
  enableFocus = () => {
    this.setState({
      isFocusEnabled: true
    });
  };
  disableFocus = () => {
    this.setState({
      isFocusEnabled: false
    });
  };
  focus = (id) => {
    this.setState((previousState) => {
      const hasFocusableId = previousState.focusables.some((focusable) => focusable?.id === id);
      if (!hasFocusableId) {
        return previousState;
      }
      return { activeFocusId: id };
    });
  };
  focusNext = () => {
    this.setState((previousState) => {
      const firstFocusableId = previousState.focusables.find((focusable) => focusable.isActive)?.id;
      const nextFocusableId = this.findNextFocusable(previousState);
      return {
        activeFocusId: nextFocusableId ?? firstFocusableId
      };
    });
  };
  focusPrevious = () => {
    this.setState((previousState) => {
      const lastFocusableId = previousState.focusables.findLast((focusable) => focusable.isActive)?.id;
      const previousFocusableId = this.findPreviousFocusable(previousState);
      return {
        activeFocusId: previousFocusableId ?? lastFocusableId
      };
    });
  };
  addFocusable = (id, { autoFocus }) => {
    this.setState((previousState) => {
      let nextFocusId = previousState.activeFocusId;
      if (!nextFocusId && autoFocus) {
        nextFocusId = id;
      }
      return {
        activeFocusId: nextFocusId,
        focusables: [
          ...previousState.focusables,
          {
            id,
            isActive: true
          }
        ]
      };
    });
  };
  removeFocusable = (id) => {
    this.setState((previousState) => ({
      activeFocusId: previousState.activeFocusId === id ? undefined : previousState.activeFocusId,
      focusables: previousState.focusables.filter((focusable) => {
        return focusable.id !== id;
      })
    }));
  };
  activateFocusable = (id) => {
    this.setState((previousState) => ({
      focusables: previousState.focusables.map((focusable) => {
        if (focusable.id !== id) {
          return focusable;
        }
        return {
          id,
          isActive: true
        };
      })
    }));
  };
  deactivateFocusable = (id) => {
    this.setState((previousState) => ({
      activeFocusId: previousState.activeFocusId === id ? undefined : previousState.activeFocusId,
      focusables: previousState.focusables.map((focusable) => {
        if (focusable.id !== id) {
          return focusable;
        }
        return {
          id,
          isActive: false
        };
      })
    }));
  };
  findNextFocusable = (state) => {
    const activeIndex = state.focusables.findIndex((focusable) => {
      return focusable.id === state.activeFocusId;
    });
    for (let index = activeIndex + 1;index < state.focusables.length; index++) {
      const focusable = state.focusables[index];
      if (focusable?.isActive) {
        return focusable.id;
      }
    }
    return;
  };
  findPreviousFocusable = (state) => {
    const activeIndex = state.focusables.findIndex((focusable) => {
      return focusable.id === state.activeFocusId;
    });
    for (let index = activeIndex - 1;index >= 0; index--) {
      const focusable = state.focusables[index];
      if (focusable?.isActive) {
        return focusable.id;
      }
    }
    return;
  };
}

// node_modules/ink/build/ink.js
var noop2 = () => {};

class Ink {
  options;
  log;
  throttledLog;
  isUnmounted;
  lastOutput;
  container;
  rootNode;
  fullStaticOutput;
  exitPromise;
  restoreConsole;
  unsubscribeResize;
  constructor(options) {
    autoBind(this);
    this.options = options;
    this.rootNode = createNode("ink-root");
    this.rootNode.onComputeLayout = this.calculateLayout;
    this.rootNode.onRender = options.debug ? this.onRender : throttle(this.onRender, 32, {
      leading: true,
      trailing: true
    });
    this.rootNode.onImmediateRender = this.onRender;
    this.log = log_update_default.create(options.stdout);
    this.throttledLog = options.debug ? this.log : throttle(this.log, undefined, {
      leading: true,
      trailing: true
    });
    this.isUnmounted = false;
    this.lastOutput = "";
    this.fullStaticOutput = "";
    this.container = reconciler_default.createContainer(this.rootNode, 0, null, false, null, "id", () => {}, null);
    this.unsubscribeExit = import_signal_exit2.default(this.unmount, { alwaysLast: false });
    if (process11.env["DEV"] === "true") {
      reconciler_default.injectIntoDevTools({
        bundleType: 0,
        version: "16.13.1",
        rendererPackageName: "ink"
      });
    }
    if (options.patchConsole) {
      this.patchConsole();
    }
    if (!is_in_ci_default) {
      options.stdout.on("resize", this.resized);
      this.unsubscribeResize = () => {
        options.stdout.off("resize", this.resized);
      };
    }
  }
  resized = () => {
    this.calculateLayout();
    this.onRender();
  };
  resolveExitPromise = () => {};
  rejectExitPromise = () => {};
  unsubscribeExit = () => {};
  calculateLayout = () => {
    const terminalWidth = this.options.stdout.columns || 80;
    this.rootNode.yogaNode.setWidth(terminalWidth);
    this.rootNode.yogaNode.calculateLayout(undefined, undefined, src_default.DIRECTION_LTR);
  };
  onRender = () => {
    if (this.isUnmounted) {
      return;
    }
    const { output, outputHeight, staticOutput } = renderer_default(this.rootNode);
    const hasStaticOutput = staticOutput && staticOutput !== `
`;
    if (this.options.debug) {
      if (hasStaticOutput) {
        this.fullStaticOutput += staticOutput;
      }
      this.options.stdout.write(this.fullStaticOutput + output);
      return;
    }
    if (is_in_ci_default) {
      if (hasStaticOutput) {
        this.options.stdout.write(staticOutput);
      }
      this.lastOutput = output;
      return;
    }
    if (hasStaticOutput) {
      this.fullStaticOutput += staticOutput;
    }
    if (outputHeight >= this.options.stdout.rows) {
      this.options.stdout.write(exports_base.clearTerminal + this.fullStaticOutput + output);
      this.lastOutput = output;
      return;
    }
    if (hasStaticOutput) {
      this.log.clear();
      this.options.stdout.write(staticOutput);
      this.log(output);
    }
    if (!hasStaticOutput && output !== this.lastOutput) {
      this.throttledLog(output);
    }
    this.lastOutput = output;
  };
  render(node) {
    const tree = import_react10.default.createElement(App, { stdin: this.options.stdin, stdout: this.options.stdout, stderr: this.options.stderr, writeToStdout: this.writeToStdout, writeToStderr: this.writeToStderr, exitOnCtrlC: this.options.exitOnCtrlC, onExit: this.unmount }, node);
    reconciler_default.updateContainer(tree, this.container, null, noop2);
  }
  writeToStdout(data) {
    if (this.isUnmounted) {
      return;
    }
    if (this.options.debug) {
      this.options.stdout.write(data + this.fullStaticOutput + this.lastOutput);
      return;
    }
    if (is_in_ci_default) {
      this.options.stdout.write(data);
      return;
    }
    this.log.clear();
    this.options.stdout.write(data);
    this.log(this.lastOutput);
  }
  writeToStderr(data) {
    if (this.isUnmounted) {
      return;
    }
    if (this.options.debug) {
      this.options.stderr.write(data);
      this.options.stdout.write(this.fullStaticOutput + this.lastOutput);
      return;
    }
    if (is_in_ci_default) {
      this.options.stderr.write(data);
      return;
    }
    this.log.clear();
    this.options.stderr.write(data);
    this.log(this.lastOutput);
  }
  unmount(error) {
    if (this.isUnmounted) {
      return;
    }
    this.calculateLayout();
    this.onRender();
    this.unsubscribeExit();
    if (typeof this.restoreConsole === "function") {
      this.restoreConsole();
    }
    if (typeof this.unsubscribeResize === "function") {
      this.unsubscribeResize();
    }
    if (is_in_ci_default) {
      this.options.stdout.write(this.lastOutput + `
`);
    } else if (!this.options.debug) {
      this.log.done();
    }
    this.isUnmounted = true;
    reconciler_default.updateContainer(null, this.container, null, noop2);
    instances_default.delete(this.options.stdout);
    if (error instanceof Error) {
      this.rejectExitPromise(error);
    } else {
      this.resolveExitPromise();
    }
  }
  async waitUntilExit() {
    this.exitPromise ||= new Promise((resolve, reject2) => {
      this.resolveExitPromise = resolve;
      this.rejectExitPromise = reject2;
    });
    return this.exitPromise;
  }
  clear() {
    if (!is_in_ci_default && !this.options.debug) {
      this.log.clear();
    }
  }
  patchConsole() {
    if (this.options.debug) {
      return;
    }
    this.restoreConsole = dist_default((stream, data) => {
      if (stream === "stdout") {
        this.writeToStdout(data);
      }
      if (stream === "stderr") {
        const isReactMessage = data.startsWith("The above error occurred");
        if (!isReactMessage) {
          this.writeToStderr(data);
        }
      }
    });
  }
}

// node_modules/ink/build/render.js
var render = (node, options) => {
  const inkOptions = {
    stdout: process12.stdout,
    stdin: process12.stdin,
    stderr: process12.stderr,
    debug: false,
    exitOnCtrlC: true,
    patchConsole: true,
    ...getOptions(options)
  };
  const instance = getInstance(inkOptions.stdout, () => new Ink(inkOptions));
  instance.render(node);
  return {
    rerender: instance.render,
    unmount() {
      instance.unmount();
    },
    waitUntilExit: instance.waitUntilExit,
    cleanup: () => instances_default.delete(inkOptions.stdout),
    clear: instance.clear
  };
};
var render_default = render;
var getOptions = (stdout = {}) => {
  if (stdout instanceof Stream) {
    return {
      stdout,
      stdin: process12.stdin
    };
  }
  return stdout;
};
var getInstance = (stdout, createInstance) => {
  let instance = instances_default.get(stdout);
  if (!instance) {
    instance = createInstance();
    instances_default.set(stdout, instance);
  }
  return instance;
};
// node_modules/ink/build/components/Static.js
var import_react11 = __toESM(require_react(), 1);
// node_modules/ink/build/components/Transform.js
var import_react12 = __toESM(require_react(), 1);
// node_modules/ink/build/components/Newline.js
var import_react13 = __toESM(require_react(), 1);
// node_modules/ink/build/components/Spacer.js
var import_react14 = __toESM(require_react(), 1);
// node_modules/ink/build/hooks/use-input.js
var import_react16 = __toESM(require_react(), 1);

// node_modules/ink/build/parse-keypress.js
import { Buffer as Buffer2 } from "node:buffer";
var metaKeyCodeRe = /^(?:\x1b)([a-zA-Z0-9])$/;
var fnKeyRe = /^(?:\x1b+)(O|N|\[|\[\[)(?:(\d+)(?:;(\d+))?([~^$])|(?:1;)?(\d+)?([a-zA-Z]))/;
var keyName = {
  OP: "f1",
  OQ: "f2",
  OR: "f3",
  OS: "f4",
  "[11~": "f1",
  "[12~": "f2",
  "[13~": "f3",
  "[14~": "f4",
  "[[A": "f1",
  "[[B": "f2",
  "[[C": "f3",
  "[[D": "f4",
  "[[E": "f5",
  "[15~": "f5",
  "[17~": "f6",
  "[18~": "f7",
  "[19~": "f8",
  "[20~": "f9",
  "[21~": "f10",
  "[23~": "f11",
  "[24~": "f12",
  "[A": "up",
  "[B": "down",
  "[C": "right",
  "[D": "left",
  "[E": "clear",
  "[F": "end",
  "[H": "home",
  OA: "up",
  OB: "down",
  OC: "right",
  OD: "left",
  OE: "clear",
  OF: "end",
  OH: "home",
  "[1~": "home",
  "[2~": "insert",
  "[3~": "delete",
  "[4~": "end",
  "[5~": "pageup",
  "[6~": "pagedown",
  "[[5~": "pageup",
  "[[6~": "pagedown",
  "[7~": "home",
  "[8~": "end",
  "[a": "up",
  "[b": "down",
  "[c": "right",
  "[d": "left",
  "[e": "clear",
  "[2$": "insert",
  "[3$": "delete",
  "[5$": "pageup",
  "[6$": "pagedown",
  "[7$": "home",
  "[8$": "end",
  Oa: "up",
  Ob: "down",
  Oc: "right",
  Od: "left",
  Oe: "clear",
  "[2^": "insert",
  "[3^": "delete",
  "[5^": "pageup",
  "[6^": "pagedown",
  "[7^": "home",
  "[8^": "end",
  "[Z": "tab"
};
var nonAlphanumericKeys = [...Object.values(keyName), "backspace"];
var isShiftKey = (code) => {
  return [
    "[a",
    "[b",
    "[c",
    "[d",
    "[e",
    "[2$",
    "[3$",
    "[5$",
    "[6$",
    "[7$",
    "[8$",
    "[Z"
  ].includes(code);
};
var isCtrlKey = (code) => {
  return [
    "Oa",
    "Ob",
    "Oc",
    "Od",
    "Oe",
    "[2^",
    "[3^",
    "[5^",
    "[6^",
    "[7^",
    "[8^"
  ].includes(code);
};
var parseKeypress = (s = "") => {
  let parts;
  if (Buffer2.isBuffer(s)) {
    if (s[0] > 127 && s[1] === undefined) {
      s[0] -= 128;
      s = "\x1B" + String(s);
    } else {
      s = String(s);
    }
  } else if (s !== undefined && typeof s !== "string") {
    s = String(s);
  } else if (!s) {
    s = "";
  }
  const key = {
    name: "",
    ctrl: false,
    meta: false,
    shift: false,
    option: false,
    sequence: s,
    raw: s
  };
  key.sequence = key.sequence || s || key.name;
  if (s === "\r") {
    key.raw = undefined;
    key.name = "return";
  } else if (s === `
`) {
    key.name = "enter";
  } else if (s === "\t") {
    key.name = "tab";
  } else if (s === "\b" || s === "\x1B\b") {
    key.name = "backspace";
    key.meta = s.charAt(0) === "\x1B";
  } else if (s === "" || s === "\x1B") {
    key.name = "delete";
    key.meta = s.charAt(0) === "\x1B";
  } else if (s === "\x1B" || s === "\x1B\x1B") {
    key.name = "escape";
    key.meta = s.length === 2;
  } else if (s === " " || s === "\x1B ") {
    key.name = "space";
    key.meta = s.length === 2;
  } else if (s.length === 1 && s <= "\x1A") {
    key.name = String.fromCharCode(s.charCodeAt(0) + 97 - 1);
    key.ctrl = true;
  } else if (s.length === 1 && s >= "0" && s <= "9") {
    key.name = "number";
  } else if (s.length === 1 && s >= "a" && s <= "z") {
    key.name = s;
  } else if (s.length === 1 && s >= "A" && s <= "Z") {
    key.name = s.toLowerCase();
    key.shift = true;
  } else if (parts = metaKeyCodeRe.exec(s)) {
    key.meta = true;
    key.shift = /^[A-Z]$/.test(parts[1]);
  } else if (parts = fnKeyRe.exec(s)) {
    const segs = [...s];
    if (segs[0] === "\x1B" && segs[1] === "\x1B") {
      key.option = true;
    }
    const code = [parts[1], parts[2], parts[4], parts[6]].filter(Boolean).join("");
    const modifier = (parts[3] || parts[5] || 1) - 1;
    key.ctrl = !!(modifier & 4);
    key.meta = !!(modifier & 10);
    key.shift = !!(modifier & 1);
    key.code = code;
    key.name = keyName[code];
    key.shift = isShiftKey(code) || key.shift;
    key.ctrl = isCtrlKey(code) || key.ctrl;
  }
  return key;
};
var parse_keypress_default = parseKeypress;

// node_modules/ink/build/hooks/use-stdin.js
var import_react15 = __toESM(require_react(), 1);
var useStdin = () => import_react15.useContext(StdinContext_default);
var use_stdin_default = useStdin;

// node_modules/ink/build/hooks/use-input.js
var useInput = (inputHandler, options = {}) => {
  const { stdin, setRawMode, internal_exitOnCtrlC, internal_eventEmitter } = use_stdin_default();
  import_react16.useEffect(() => {
    if (options.isActive === false) {
      return;
    }
    setRawMode(true);
    return () => {
      setRawMode(false);
    };
  }, [options.isActive, setRawMode]);
  import_react16.useEffect(() => {
    if (options.isActive === false) {
      return;
    }
    const handleData = (data) => {
      const keypress = parse_keypress_default(data);
      const key = {
        upArrow: keypress.name === "up",
        downArrow: keypress.name === "down",
        leftArrow: keypress.name === "left",
        rightArrow: keypress.name === "right",
        pageDown: keypress.name === "pagedown",
        pageUp: keypress.name === "pageup",
        return: keypress.name === "return",
        escape: keypress.name === "escape",
        ctrl: keypress.ctrl,
        shift: keypress.shift,
        tab: keypress.name === "tab",
        backspace: keypress.name === "backspace",
        delete: keypress.name === "delete",
        meta: keypress.meta || keypress.name === "escape" || keypress.option
      };
      let input = keypress.ctrl ? keypress.name : keypress.sequence;
      if (nonAlphanumericKeys.includes(keypress.name)) {
        input = "";
      }
      if (input.startsWith("\x1B")) {
        input = input.slice(1);
      }
      if (input.length === 1 && typeof input[0] === "string" && /[A-Z]/.test(input[0])) {
        key.shift = true;
      }
      if (!(input === "c" && key.ctrl) || !internal_exitOnCtrlC) {
        reconciler_default.batchedUpdates(() => {
          inputHandler(input, key);
        });
      }
    };
    internal_eventEmitter?.on("input", handleData);
    return () => {
      internal_eventEmitter?.removeListener("input", handleData);
    };
  }, [options.isActive, stdin, internal_exitOnCtrlC, inputHandler]);
};
var use_input_default = useInput;
// node_modules/ink/build/hooks/use-app.js
var import_react17 = __toESM(require_react(), 1);
var useApp = () => import_react17.useContext(AppContext_default);
var use_app_default = useApp;
// node_modules/ink/build/hooks/use-stdout.js
var import_react18 = __toESM(require_react(), 1);
var useStdout = () => import_react18.useContext(StdoutContext_default);
var use_stdout_default = useStdout;
// node_modules/ink/build/hooks/use-stderr.js
var import_react19 = __toESM(require_react(), 1);
// node_modules/ink/build/hooks/use-focus.js
var import_react20 = __toESM(require_react(), 1);
// node_modules/ink/build/hooks/use-focus-manager.js
var import_react21 = __toESM(require_react(), 1);
// src/main.tsx
var import_react31 = __toESM(require_react(), 1);

// src/components/AskQuestionOverlay.tsx
var jsx_runtime = __toESM(require_jsx_runtime(), 1);
function AskQuestionOverlay({
  questions,
  focusedIdx,
  selections,
  palette
}) {
  return /* @__PURE__ */ jsx_runtime.jsxs(Box_default, {
    flexDirection: "column",
    borderStyle: "round",
    borderColor: palette.accent,
    paddingX: 1,
    children: [
      /* @__PURE__ */ jsx_runtime.jsxs(Box_default, {
        marginBottom: 1,
        children: [
          /* @__PURE__ */ jsx_runtime.jsx(Text, {
            color: palette.accent,
            bold: true,
            children: "? Athena needs your input"
          }),
          /* @__PURE__ */ jsx_runtime.jsxs(Text, {
            color: palette.primary_faint,
            children: [
              "   ",
              "↑↓ pick · Tab next question · Enter send · Esc cancel"
            ]
          })
        ]
      }),
      questions.map((q, qi) => /* @__PURE__ */ jsx_runtime.jsxs(Box_default, {
        flexDirection: "column",
        marginBottom: 1,
        children: [
          q.header && /* @__PURE__ */ jsx_runtime.jsxs(Text, {
            color: palette.accent_dim,
            children: [
              "── ",
              q.header,
              " ──"
            ]
          }),
          /* @__PURE__ */ jsx_runtime.jsxs(Text, {
            bold: true,
            color: qi === focusedIdx ? palette.accent : palette.primary,
            children: [
              qi === focusedIdx ? "▸ " : "  ",
              q.question
            ]
          }),
          renderOptions(q, qi, focusedIdx, selections[qi], palette)
        ]
      }, qi))
    ]
  });
}
function renderOptions(q, qi, focusedIdx, sel, palette) {
  const opts = q.options ?? [];
  const total = opts.length;
  const isFocused = qi === focusedIdx;
  const multi = !!q.multiSelect;
  const isSelected = (idx) => {
    if (sel === null)
      return false;
    if (Array.isArray(sel))
      return sel.includes(idx);
    return sel === idx;
  };
  const rows = [];
  for (let i = 0;i < total; i++) {
    const opt = opts[i];
    rows.push(/* @__PURE__ */ jsx_runtime.jsxs(Box_default, {
      children: [
        /* @__PURE__ */ jsx_runtime.jsx(Text, {
          color: palette.primary_faint,
          children: "    "
        }),
        /* @__PURE__ */ jsx_runtime.jsx(Text, {
          color: isSelected(i) ? palette.accent : palette.primary_dim,
          children: multi ? isSelected(i) ? "[x] " : "[ ] " : isSelected(i) ? "▸ " : "  "
        }),
        /* @__PURE__ */ jsx_runtime.jsxs(Text, {
          color: isSelected(i) ? palette.accent : palette.primary_dim,
          bold: isSelected(i),
          children: [
            i + 1,
            ". ",
            opt.label
          ]
        }),
        /* @__PURE__ */ jsx_runtime.jsxs(Text, {
          color: palette.primary_faint,
          children: [
            "  — ",
            opt.description
          ]
        })
      ]
    }, i));
  }
  rows.push(/* @__PURE__ */ jsx_runtime.jsxs(Box_default, {
    children: [
      /* @__PURE__ */ jsx_runtime.jsx(Text, {
        color: palette.primary_faint,
        children: "    "
      }),
      /* @__PURE__ */ jsx_runtime.jsx(Text, {
        color: isSelected(total) ? palette.accent : palette.primary_dim,
        children: multi ? isSelected(total) ? "[x] " : "[ ] " : isSelected(total) ? "▸ " : "  "
      }),
      /* @__PURE__ */ jsx_runtime.jsxs(Text, {
        color: isSelected(total) ? palette.accent : palette.primary_dim,
        italic: true,
        children: [
          total + 1,
          ". Other (free-form)"
        ]
      })
    ]
  }, "other"));
  if (isFocused) {
    rows.push(/* @__PURE__ */ jsx_runtime.jsxs(Text, {
      color: palette.primary_faint,
      dimColor: true,
      children: [
        "      ",
        "↑↓ to move",
        multi ? " · Space to toggle" : ""
      ]
    }, "hint"));
  }
  return /* @__PURE__ */ jsx_runtime.jsx(Box_default, {
    flexDirection: "column",
    children: rows
  });
}

// src/components/AtMentionPopup.tsx
var jsx_runtime2 = __toESM(require_jsx_runtime(), 1);
function AtMentionPopup({
  matches: matches2,
  selectedIdx,
  palette
}) {
  if (matches2.length === 0)
    return null;
  const sel = Math.min(Math.max(0, selectedIdx), matches2.length - 1);
  return /* @__PURE__ */ jsx_runtime2.jsx(Box_default, {
    flexDirection: "column",
    marginLeft: 2,
    children: matches2.map((m, i) => {
      const isSel = i === sel;
      return /* @__PURE__ */ jsx_runtime2.jsxs(Box_default, {
        children: [
          /* @__PURE__ */ jsx_runtime2.jsx(Text, {
            color: isSel ? palette.accent : palette.primary_dim,
            children: isSel ? "▸ " : "  "
          }),
          /* @__PURE__ */ jsx_runtime2.jsx(Text, {
            color: isSel ? palette.accent : palette.primary_dim,
            bold: isSel,
            children: m
          })
        ]
      }, m);
    })
  });
}

// src/components/SlashPopup.tsx
var jsx_runtime3 = __toESM(require_jsx_runtime(), 1);
var SLASH_COMMANDS = [
  { name: "/help", description: "show slash-command reference" },
  { name: "/model", description: "switch model (arg: NAME)" },
  { name: "/models", description: "list available Ollama models" },
  { name: "/tools", description: "list registered tools (built-in + MCP)" },
  { name: "/mcp", description: "list MCP servers (or 'logs NAME' for stderr)" },
  { name: "/clear", description: "reset conversation (keeps system prompt)" },
  { name: "/cost", description: "token usage + elapsed time" },
  { name: "/status", description: "session snapshot (model, tokens, retries)" },
  { name: "/save", description: "save transcript (arg: file path)" },
  { name: "/dump", description: "print the live system prompt" },
  { name: "/cwd", description: "show or change workspace (arg: path)" },
  { name: "/init", description: "generate ATHENA.md from workspace survey" },
  { name: "/review", description: "review pending changes (arg: git ref)" },
  { name: "/security-review", description: "security-focused review of pending changes" },
  { name: "/loop", description: "run a prompt on a timer (args: INTERVAL CMD)" },
  { name: "/loop-stop", description: "stop a running /loop" },
  { name: "/checkpoint", description: "snapshot workspace + agent state (arg: name)" },
  { name: "/checkpoints", description: "list checkpoints in this session" },
  { name: "/compact", description: "summarize history and replace it" },
  { name: "/resume", description: "resume a saved transcript (arg: file)" },
  { name: "/memory", description: "inspect/edit persistent memory (subcmd)" },
  { name: "/plan", description: "enter plan mode (read-only investigation)" },
  { name: "/plan-exit", description: "leave plan mode without executing" },
  { name: "/steer", description: "queue MSG for next prompt (or 'clear')" },
  { name: "/queue", description: "list pending steers" },
  { name: "/goal", description: "set/pause/resume/inspect/clear active goal" },
  { name: "/subgoal", description: "append (arg: MSG) or 'done' the next subgoal" },
  { name: "/board", description: "render the kanban (or 'clear' to wipe)" },
  { name: "/computer", description: "show computer-use status (backend, mode, allow/deny)" },
  { name: "/skill", description: "import a SKILL.md / dir / archive, or 'reload'" },
  { name: "/video", description: "video backends: list/set/clear" },
  { name: "/theme", description: "TUI palette: list, 'set NAME', or 'save'" },
  { name: "/hooks", description: "list configured hooks" },
  { name: "/godmode", description: "jailbreak toolkit (gated: ATHENA_ALLOW_GODMODE=1)" },
  { name: "/exit", description: "quit" }
];
function matchSlashCommands(query, limit = 7) {
  const q = query.toLowerCase();
  if (!q.startsWith("/"))
    return [];
  const hits = SLASH_COMMANDS.filter((c) => c.name.toLowerCase().startsWith(q));
  return hits.slice(0, limit);
}
function SlashPopup({
  query,
  selectedIdx,
  palette
}) {
  const matches2 = matchSlashCommands(query);
  if (matches2.length === 0)
    return null;
  const sel = Math.min(Math.max(0, selectedIdx), matches2.length - 1);
  const nameWidth = matches2.reduce((w, m) => Math.max(w, m.name.length), 0);
  return /* @__PURE__ */ jsx_runtime3.jsx(Box_default, {
    flexDirection: "column",
    marginLeft: 2,
    children: matches2.map((m, i) => {
      const isSel = i === sel;
      const namePadded = m.name.padEnd(nameWidth + 2);
      return /* @__PURE__ */ jsx_runtime3.jsxs(Box_default, {
        children: [
          /* @__PURE__ */ jsx_runtime3.jsx(Text, {
            color: isSel ? palette.accent : palette.primary_dim,
            children: isSel ? "▸ " : "  "
          }),
          /* @__PURE__ */ jsx_runtime3.jsx(Text, {
            color: isSel ? palette.accent : palette.primary_dim,
            bold: isSel,
            children: namePadded
          }),
          /* @__PURE__ */ jsx_runtime3.jsx(Text, {
            color: palette.primary_faint,
            children: m.description
          })
        ]
      }, m.name);
    })
  });
}
function completionText(selected) {
  return selected.name + " ";
}

// src/hooks/useTokenRate.ts
var import_react22 = __toESM(require_react(), 1);
function useTokenRate(totalTokens, options = {}) {
  const buckets = options.buckets ?? 16;
  const windowSec = options.windowSec ?? 30;
  const bucketSec = windowSec / buckets;
  const samples = import_react22.useRef([]);
  const [state, setState] = import_react22.useState({
    current: 0,
    history: new Array(buckets).fill(0)
  });
  import_react22.useEffect(() => {
    const now2 = performance.now();
    const oldestAllowed = now2 - windowSec * 1000;
    samples.current.push([now2, totalTokens]);
    samples.current = samples.current.filter(([t]) => t >= oldestAllowed);
    if (samples.current.length < 2) {
      return;
    }
    const history = [];
    const windowStartMs = now2 - windowSec * 1000;
    for (let i = 0;i < buckets; i++) {
      const bStart = windowStartMs + i * bucketSec * 1000;
      const bEnd = bStart + bucketSec * 1000;
      const inBucket = samples.current.filter(([t]) => t >= bStart && t < bEnd);
      const first = inBucket[0];
      const last2 = inBucket[inBucket.length - 1];
      if (inBucket.length < 2 || !first || !last2) {
        history.push(0);
        continue;
      }
      const tokensDelta = last2[1] - first[1];
      const dtSec = (last2[0] - first[0]) / 1000;
      history.push(dtSec > 0 ? tokensDelta / dtSec : 0);
    }
    const tailStart = now2 - 5000;
    const tail2 = samples.current.filter(([t]) => t >= tailStart);
    let current = 0;
    const tailFirst = tail2[0];
    const tailLast = tail2[tail2.length - 1];
    if (tail2.length >= 2 && tailFirst && tailLast) {
      const tokensDelta = tailLast[1] - tailFirst[1];
      const dtSec = (tailLast[0] - tailFirst[0]) / 1000;
      current = dtSec > 0 ? tokensDelta / dtSec : 0;
    }
    setState({ current, history });
  }, [totalTokens, buckets, windowSec, bucketSec]);
  return state;
}
function renderSparkline(history) {
  const bars = "▁▂▃▄▅▆▇█";
  const max2 = Math.max(...history, 1);
  return history.map((v) => bars[Math.min(bars.length - 1, Math.floor(v / max2 * bars.length))]).join("");
}

// src/components/StatusBar.tsx
var jsx_runtime4 = __toESM(require_jsx_runtime(), 1);
function StatusBar({
  status,
  palette,
  tpsHistory = [],
  tpsCurrent = 0,
  termCols = 999
}) {
  if (!status) {
    return /* @__PURE__ */ jsx_runtime4.jsx(Box_default, {
      children: /* @__PURE__ */ jsx_runtime4.jsx(Text, {
        color: palette.primary_faint,
        children: "…"
      })
    });
  }
  const showTheme = termCols >= 100;
  const showSparkline = termCols >= 90;
  const showTools = termCols >= 80;
  const showProfile = termCols >= 70;
  const showTokens = termCols >= 60;
  const leftSegments = [];
  if (status.model) {
    leftSegments.push(/* @__PURE__ */ jsx_runtime4.jsxs(Text, {
      color: palette.accent,
      children: [
        "▰▰",
        " "
      ]
    }, "prompt"));
    leftSegments.push(/* @__PURE__ */ jsx_runtime4.jsx(Text, {
      color: palette.accent_dim,
      children: status.model
    }, "model"));
  }
  if (status.profile && showProfile) {
    leftSegments.push(/* @__PURE__ */ jsx_runtime4.jsxs(Text, {
      color: palette.primary_dim,
      children: [
        " · ",
        status.profile
      ]
    }, "profile"));
  }
  if (status.tool_summary && showTools) {
    leftSegments.push(/* @__PURE__ */ jsx_runtime4.jsxs(Text, {
      color: palette.primary_dim,
      children: [
        " · ",
        status.tool_summary
      ]
    }, "tools"));
  }
  const rightSegments = [];
  if (status.elapsed_seconds !== undefined && status.elapsed_seconds !== null) {
    rightSegments.push(/* @__PURE__ */ jsx_runtime4.jsx(Text, {
      color: palette.primary_dim,
      children: formatDuration(status.elapsed_seconds)
    }, "elapsed"));
  }
  const hasTokens = status.tokens_up !== undefined && status.tokens_up !== null || status.tokens_down !== undefined && status.tokens_down !== null;
  if (hasTokens && showTokens) {
    rightSegments.push(/* @__PURE__ */ jsx_runtime4.jsxs(Text, {
      color: palette.primary_dim,
      children: [
        rightSegments.length > 0 ? " · " : "",
        "↑",
        (status.tokens_up ?? 0).toLocaleString(),
        " ↓",
        (status.tokens_down ?? 0).toLocaleString()
      ]
    }, "tokens"));
  }
  const hasEverHadActivity = tpsHistory.length > 0 && tpsHistory.some((v) => v > 0);
  if (hasEverHadActivity && showSparkline) {
    const spark = renderSparkline(tpsHistory);
    const rateText = tpsCurrent >= 1 ? `${Math.round(tpsCurrent)}/s` : tpsCurrent > 0 ? `${tpsCurrent.toFixed(1)}/s` : "idle";
    const rateColor = tpsCurrent > 0 ? palette.accent_dim : palette.primary_faint;
    rightSegments.push(/* @__PURE__ */ jsx_runtime4.jsxs(Text, {
      children: [
        /* @__PURE__ */ jsx_runtime4.jsx(Text, {
          color: palette.primary_faint,
          children: " · "
        }),
        /* @__PURE__ */ jsx_runtime4.jsx(Text, {
          color: palette.accent_dim,
          children: spark
        }),
        /* @__PURE__ */ jsx_runtime4.jsxs(Text, {
          color: rateColor,
          children: [
            " ",
            rateText
          ]
        })
      ]
    }, "tps"));
  }
  if (showTheme) {
    rightSegments.push(/* @__PURE__ */ jsx_runtime4.jsxs(Text, {
      color: palette.primary_faint,
      children: [
        rightSegments.length > 0 ? "  ·  " : "",
        palette.name
      ]
    }, "theme"));
  }
  return /* @__PURE__ */ jsx_runtime4.jsxs(Box_default, {
    justifyContent: "space-between",
    children: [
      /* @__PURE__ */ jsx_runtime4.jsx(Box_default, {
        children: leftSegments
      }),
      /* @__PURE__ */ jsx_runtime4.jsx(Box_default, {
        children: rightSegments
      })
    ]
  });
}
function formatDuration(seconds) {
  if (seconds < 60)
    return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m2 = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m2}m${s}s` : `${m2}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor(seconds % 3600 / 60);
  return m > 0 ? `${h}h${m}m` : `${h}h`;
}

// src/hooks/useTicker.ts
var import_react23 = __toESM(require_react(), 1);
function useTicker(intervalMs, paused = false) {
  const [tick, setTick] = import_react23.useState(0);
  import_react23.useEffect(() => {
    if (paused)
      return;
    const t = setInterval(() => setTick((n) => n + 1), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs, paused]);
  return tick;
}

// src/components/StuckIndicator.tsx
var jsx_runtime5 = __toESM(require_jsx_runtime(), 1);
function StuckIndicator({
  state,
  palette,
  stuckThresholdMs = 30000
}) {
  useTicker(1000);
  const inFlight = state.streamId !== null || state.toolLane.length > 0 || state._pendingUserInputSince !== null;
  if (!inFlight)
    return null;
  const referencePoints = [];
  if (state._lastProgressMs > 0)
    referencePoints.push(state._lastProgressMs);
  if (state._pendingUserInputSince !== null) {
    referencePoints.push(state._pendingUserInputSince);
  }
  for (const t of state.toolLane) {
    referencePoints.push(t.startedAtMs);
  }
  if (referencePoints.length === 0)
    return null;
  const mostRecent = Math.max(...referencePoints);
  const stuckMs = performance.now() - mostRecent;
  if (stuckMs < stuckThresholdMs)
    return null;
  const stuckSeconds = Math.round(stuckMs / 1000);
  return /* @__PURE__ */ jsx_runtime5.jsxs(Box_default, {
    children: [
      /* @__PURE__ */ jsx_runtime5.jsx(Text, {
        color: palette.primary_faint,
        children: "· "
      }),
      /* @__PURE__ */ jsx_runtime5.jsxs(Text, {
        color: palette.accent_dim,
        children: [
          "stalled ",
          stuckSeconds,
          "s"
        ]
      }),
      /* @__PURE__ */ jsx_runtime5.jsx(Text, {
        color: palette.primary_faint,
        children: " — press ESC to interrupt"
      })
    ]
  });
}

// src/components/Spinner.tsx
var jsx_runtime6 = __toESM(require_jsx_runtime(), 1);
var HALF_MOONS = ["◐", "◓", "◑", "◒"];
var DOTS = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"];
function Spinner({ variant = "half_moon", color }) {
  const frames = variant === "dots" ? DOTS : HALF_MOONS;
  const interval = variant === "dots" ? 83 : 125;
  const tick = useTicker(interval);
  const glyph = frames[tick % frames.length];
  return /* @__PURE__ */ jsx_runtime6.jsx(Text, {
    color,
    children: glyph
  });
}

// src/components/ToolLaneRow.tsx
var jsx_runtime7 = __toESM(require_jsx_runtime(), 1);
function ToolLaneRow({
  tool,
  args,
  startedAtMs,
  palette,
  stillWorkingThresholdMs = 15000
}) {
  useTicker(1000);
  const elapsedMs = Math.max(0, performance.now() - startedAtMs);
  const elapsedSec = Math.floor(elapsedMs / 1000);
  const accent = palette?.accent ?? "yellow";
  const dim = palette?.accent_dim ?? "yellow";
  const faint = palette?.primary_faint ?? "gray";
  const showStillWorking = elapsedMs > stillWorkingThresholdMs;
  return /* @__PURE__ */ jsx_runtime7.jsxs(Box_default, {
    children: [
      /* @__PURE__ */ jsx_runtime7.jsx(Spinner, {
        color: accent
      }),
      /* @__PURE__ */ jsx_runtime7.jsxs(Text, {
        color: accent,
        children: [
          " ",
          tool
        ]
      }),
      /* @__PURE__ */ jsx_runtime7.jsxs(Text, {
        color: dim,
        children: [
          "(",
          args,
          ")"
        ]
      }),
      elapsedSec >= 1 && /* @__PURE__ */ jsx_runtime7.jsxs(Text, {
        color: faint,
        children: [
          "  · ",
          _formatElapsed(elapsedSec)
        ]
      }),
      showStillWorking && /* @__PURE__ */ jsx_runtime7.jsxs(Text, {
        color: dim,
        children: [
          "  ",
          "[still working]"
        ]
      })
    ]
  });
}
function _formatElapsed(sec) {
  if (sec < 60)
    return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m${s}s` : `${m}m`;
}

// src/components/Composer.tsx
var jsx_runtime8 = __toESM(require_jsx_runtime(), 1);
function Composer({
  banner,
  status,
  toolLane,
  flash,
  confirmReq,
  inputText,
  cursorPos,
  tpsHistory,
  tpsCurrent,
  state,
  slashSelectedIdx = 0,
  termCols,
  atMatches = [],
  atSelectedIdx = 0,
  reverseSearch = null,
  askFocusedIdx = 0,
  askSelections = []
}) {
  const palette = banner?.palette ?? undefined;
  const promptColor = palette?.primary ?? "green";
  const inPlanMode = status?.plan_mode === true;
  const composerBorderColor = inPlanMode ? palette?.accent ?? "magenta" : palette?.primary_faint ?? "gray";
  return /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
    flexDirection: "column",
    children: [
      toolLane.length > 0 && /* @__PURE__ */ jsx_runtime8.jsx(Box_default, {
        flexDirection: "column",
        marginBottom: 1,
        children: toolLane.map((t) => /* @__PURE__ */ jsx_runtime8.jsx(ToolLaneRow, {
          tool: t.tool,
          args: t.args,
          startedAtMs: t.startedAtMs,
          palette
        }, t.id))
      }),
      flash && /* @__PURE__ */ jsx_runtime8.jsx(Box_default, {
        marginBottom: 0,
        children: /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
          dimColor: true,
          italic: true,
          color: flash.level === "warn" ? "yellow" : palette?.primary_dim ?? "gray",
          children: [
            flash.level === "warn" ? "! " : "· ",
            flash.text
          ]
        })
      }),
      state?.askReq && !confirmReq ? /* @__PURE__ */ jsx_runtime8.jsx(AskQuestionOverlay, {
        questions: state.askReq.questions,
        focusedIdx: askFocusedIdx,
        selections: askSelections,
        palette
      }) : reverseSearch && !confirmReq ? /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
        flexDirection: "column",
        borderStyle: "round",
        borderColor: palette?.accent ?? "yellow",
        paddingX: 1,
        children: [
          /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
            children: [
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                color: palette?.primary_faint ?? "gray",
                children: "(reverse-i-search)`"
              }),
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                color: palette?.accent ?? "yellow",
                bold: true,
                children: reverseSearch.query
              }),
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                color: palette?.primary_faint ?? "gray",
                children: "`: "
              }),
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                color: reverseSearch.match ? "white" : palette?.primary_faint ?? "gray",
                children: reverseSearch.match ?? "(no match)"
              })
            ]
          }),
          /* @__PURE__ */ jsx_runtime8.jsx(Text, {
            color: palette?.primary_dim ?? "gray",
            dimColor: true,
            children: "Ctrl+R: older  ·  Enter: accept  ·  Esc: cancel  ·  Backspace: shrink query"
          })
        ]
      }) : confirmReq ? /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
        flexDirection: "column",
        borderStyle: "round",
        borderColor: palette?.accent ?? "yellow",
        paddingX: 1,
        children: [
          confirmReq.tool_name && /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
            color: palette?.accent_dim ?? "yellow",
            children: [
              "── ",
              confirmReq.tool_name,
              " ──"
            ]
          }),
          confirmReq.preview && renderConfirmPreview(confirmReq.preview, confirmReq.preview_kind ?? "text", palette),
          /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
            bold: true,
            color: palette?.accent ?? "yellow",
            children: [
              "? ",
              confirmReq.prompt
            ]
          }),
          /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
            color: palette?.primary_dim ?? "gray",
            children: [
              confirmReq.default ? "[Y/n]" : "[y/N]",
              " ",
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                dimColor: true,
                children: "press y / n / Enter (default) / Esc"
              })
            ]
          })
        ]
      }) : /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
        flexDirection: "column",
        children: [
          inPlanMode && /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
            marginBottom: 0,
            children: [
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                color: palette?.accent ?? "magenta",
                bold: true,
                children: "◆ plan mode"
              }),
              /* @__PURE__ */ jsx_runtime8.jsx(Text, {
                color: palette?.primary_faint ?? "gray",
                children: " — write/edit/bash blocked. /plan-exit to leave."
              })
            ]
          }),
          /* @__PURE__ */ jsx_runtime8.jsx(Box_default, {
            flexDirection: "column",
            borderStyle: "round",
            borderColor: composerBorderColor,
            paddingX: 1,
            children: renderMultiLineInput(inputText, cursorPos, promptColor)
          })
        ]
      }),
      palette && !confirmReq && inputText.startsWith("/") && /* @__PURE__ */ jsx_runtime8.jsx(SlashPopup, {
        query: inputText,
        selectedIdx: slashSelectedIdx,
        palette
      }),
      palette && !confirmReq && atMatches.length > 0 && /* @__PURE__ */ jsx_runtime8.jsx(AtMentionPopup, {
        matches: atMatches,
        selectedIdx: atSelectedIdx,
        palette
      }),
      palette && state && /* @__PURE__ */ jsx_runtime8.jsx(StuckIndicator, {
        state,
        palette
      }),
      palette && /* @__PURE__ */ jsx_runtime8.jsx(StatusBar, {
        status,
        palette,
        tpsHistory,
        tpsCurrent,
        termCols
      })
    ]
  });
}
function renderConfirmPreview(preview, kind, palette) {
  const allLines = preview.split(`
`);
  const MAX = 15;
  const lines = allLines.slice(0, MAX);
  const overflow = allLines.length - lines.length;
  if (kind === "command") {
    return /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
      flexDirection: "column",
      marginY: 1,
      children: [
        lines.map((line, i) => /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
          color: palette?.accent ?? "cyan",
          children: [
            "$ ",
            line
          ]
        }, i)),
        overflow > 0 && /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
          color: palette?.primary_faint ?? "gray",
          children: [
            "… (",
            overflow,
            " more lines)"
          ]
        })
      ]
    });
  }
  if (kind === "diff") {
    return /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
      flexDirection: "column",
      marginY: 1,
      children: [
        lines.map((line, i) => {
          let color;
          let bold = false;
          if (line.startsWith("+++") || line.startsWith("---")) {
            color = palette?.primary_faint ?? "gray";
            bold = true;
          } else if (line.startsWith("@@")) {
            color = palette?.accent_dim ?? "yellow";
            bold = true;
          } else if (line.startsWith("+")) {
            color = "green";
          } else if (line.startsWith("-")) {
            color = "red";
          } else {
            color = palette?.primary_dim ?? "gray";
          }
          return /* @__PURE__ */ jsx_runtime8.jsx(Text, {
            color,
            bold,
            children: line
          }, i);
        }),
        overflow > 0 && /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
          color: palette?.primary_faint ?? "gray",
          children: [
            "… (",
            overflow,
            " more lines)"
          ]
        })
      ]
    });
  }
  if (kind === "file") {
    return /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
      flexDirection: "column",
      marginY: 1,
      children: [
        lines.map((line, i) => /* @__PURE__ */ jsx_runtime8.jsx(Text, {
          color: i === 0 ? palette?.accent ?? "cyan" : palette?.primary_dim ?? "gray",
          bold: i === 0,
          children: line
        }, i)),
        overflow > 0 && /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
          color: palette?.primary_faint ?? "gray",
          children: [
            "… (",
            overflow,
            " more lines)"
          ]
        })
      ]
    });
  }
  return /* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
    flexDirection: "column",
    marginY: 1,
    children: [
      lines.map((line, i) => /* @__PURE__ */ jsx_runtime8.jsx(Text, {
        color: palette?.primary_dim ?? "gray",
        children: line
      }, i)),
      overflow > 0 && /* @__PURE__ */ jsx_runtime8.jsxs(Text, {
        color: palette?.primary_faint ?? "gray",
        children: [
          "… (",
          overflow,
          " more lines)"
        ]
      })
    ]
  });
}
function renderMultiLineInput(text, cursor, promptColor) {
  const lines = text.split(`
`);
  const out = [];
  let charsSoFar = 0;
  for (let lineIdx = 0;lineIdx < lines.length; lineIdx++) {
    const line = lines[lineIdx];
    const lineStart = charsSoFar;
    const lineEnd = lineStart + line.length;
    const cursorInLine = cursor >= lineStart && cursor <= lineEnd ? cursor - lineStart : -1;
    charsSoFar = lineEnd + 1;
    const prefix = lineIdx === 0 ? /* @__PURE__ */ jsx_runtime8.jsx(Text, {
      color: promptColor,
      children: "▸▸ "
    }) : /* @__PURE__ */ jsx_runtime8.jsx(Text, {
      children: "   "
    });
    if (cursorInLine === -1) {
      out.push(/* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
        children: [
          prefix,
          /* @__PURE__ */ jsx_runtime8.jsx(Text, {
            children: line
          })
        ]
      }, lineIdx));
      continue;
    }
    out.push(/* @__PURE__ */ jsx_runtime8.jsxs(Box_default, {
      children: [
        prefix,
        /* @__PURE__ */ jsx_runtime8.jsx(Text, {
          children: line.slice(0, cursorInLine)
        }),
        cursorInLine < line.length ? /* @__PURE__ */ jsx_runtime8.jsxs(jsx_runtime8.Fragment, {
          children: [
            /* @__PURE__ */ jsx_runtime8.jsx(Text, {
              color: promptColor,
              inverse: true,
              children: line.charAt(cursorInLine)
            }),
            /* @__PURE__ */ jsx_runtime8.jsx(Text, {
              children: line.slice(cursorInLine + 1)
            })
          ]
        }) : /* @__PURE__ */ jsx_runtime8.jsx(Text, {
          color: promptColor,
          inverse: true,
          children: " "
        })
      ]
    }, lineIdx));
  }
  return out;
}

// src/components/Banner.tsx
var import_react25 = __toESM(require_react(), 1);

// src/components/Layout.tsx
var jsx_runtime9 = __toESM(require_jsx_runtime(), 1);
function Divider({
  palette,
  width = 38
}) {
  return /* @__PURE__ */ jsx_runtime9.jsx(Text, {
    color: palette.primary_faint,
    children: "─".repeat(Math.max(1, width))
  });
}
function Row({
  label,
  value,
  labelWidth = 8,
  labelColor,
  valueColor,
  palette
}) {
  return /* @__PURE__ */ jsx_runtime9.jsxs(Box_default, {
    children: [
      /* @__PURE__ */ jsx_runtime9.jsx(Box_default, {
        width: labelWidth,
        children: /* @__PURE__ */ jsx_runtime9.jsx(Text, {
          color: labelColor ?? palette.accent_dim,
          children: label
        })
      }),
      /* @__PURE__ */ jsx_runtime9.jsx(Text, {
        color: valueColor ?? palette.primary_dim,
        children: value
      })
    ]
  });
}

// src/components/InfoPanel.tsx
var jsx_runtime10 = __toESM(require_jsx_runtime(), 1);
var LABEL_WIDTH_IDENTITY = 7;
var LABEL_WIDTH_TOOLSET = 8;
function InfoPanel({
  model,
  cwd: cwd2,
  themeName,
  themeDescription,
  tools,
  commandsHint,
  palette,
  width,
  height
}) {
  const RENDER_SAFETY_MARGIN = 8;
  const innerW = Math.max(20, (width ?? 60) - 6 - RENDER_SAFETY_MARGIN);
  const cwdDisplay = elideMiddle(cwd2, innerW - LABEL_WIDTH_IDENTITY);
  const overflow = tools.find((t) => t.name === "…");
  const visibleTools = tools.filter((t) => t.name !== "…");
  return /* @__PURE__ */ jsx_runtime10.jsxs(Box_default, {
    borderStyle: "round",
    borderColor: palette.primary_faint,
    flexDirection: "column",
    paddingX: 2,
    paddingY: 1,
    ...width ? { width } : { flexGrow: 1 },
    ...height ? { height } : {},
    children: [
      /* @__PURE__ */ jsx_runtime10.jsxs(Box_default, {
        children: [
          /* @__PURE__ */ jsx_runtime10.jsxs(Text, {
            bold: true,
            color: palette.accent,
            children: [
              "athena",
              " "
            ]
          }),
          /* @__PURE__ */ jsx_runtime10.jsx(Text, {
            italic: true,
            color: palette.primary_dim,
            children: "· local agentic coder"
          })
        ]
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(Divider, {
        palette,
        width: innerW
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(Row, {
        palette,
        label: "model",
        value: model,
        labelWidth: LABEL_WIDTH_IDENTITY,
        valueColor: palette.accent
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(Row, {
        palette,
        label: "cwd",
        value: cwdDisplay,
        labelWidth: LABEL_WIDTH_IDENTITY,
        valueColor: palette.primary_dim
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(Row, {
        palette,
        label: "theme",
        value: themeName,
        labelWidth: LABEL_WIDTH_IDENTITY,
        valueColor: palette.primary
      }),
      themeDescription && themeDescription.length > 0 && /* @__PURE__ */ jsx_runtime10.jsx(Box_default, {
        children: /* @__PURE__ */ jsx_runtime10.jsxs(Text, {
          italic: true,
          color: palette.primary_dim,
          children: [
            " ".repeat(LABEL_WIDTH_IDENTITY),
            elideTail(themeDescription, Math.max(8, innerW - LABEL_WIDTH_IDENTITY))
          ]
        })
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(Divider, {
        palette,
        width: innerW
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(SectionHeader, {
        palette,
        label: "tools"
      }),
      visibleTools.map((toolset) => {
        const hidden = toolset.hidden_count ?? 0;
        let value = toolset.tools.join(" · ");
        if (hidden > 0)
          value += `  +${hidden}`;
        const budget = innerW - LABEL_WIDTH_TOOLSET - 2;
        return /* @__PURE__ */ jsx_runtime10.jsx(Row, {
          palette,
          label: toolset.name,
          value: elideTail(value, budget),
          labelWidth: LABEL_WIDTH_TOOLSET,
          labelColor: palette.primary_dim,
          valueColor: palette.primary_dim
        }, toolset.name);
      }),
      overflow && /* @__PURE__ */ jsx_runtime10.jsxs(Box_default, {
        marginTop: 0,
        children: [
          /* @__PURE__ */ jsx_runtime10.jsxs(Text, {
            color: palette.accent_dim,
            children: [
              "+",
              overflow.hidden_count,
              " hidden"
            ]
          }),
          /* @__PURE__ */ jsx_runtime10.jsx(Text, {
            color: palette.primary_faint,
            children: elideTail(overflow.tools.join(" · "), innerW - String(`+${overflow.hidden_count} hidden  `).length)
          })
        ]
      }),
      /* @__PURE__ */ jsx_runtime10.jsx(Divider, {
        palette,
        width: innerW
      }),
      /* @__PURE__ */ jsx_runtime10.jsxs(Box_default, {
        children: [
          /* @__PURE__ */ jsx_runtime10.jsx(SectionHeader, {
            palette,
            label: "commands"
          }),
          /* @__PURE__ */ jsx_runtime10.jsxs(Text, {
            color: palette.primary_dim,
            children: [
              "  ",
              elideTail(commandsHint, innerW - 12)
            ]
          })
        ]
      })
    ]
  });
}
function SectionHeader({
  palette,
  label
}) {
  return /* @__PURE__ */ jsx_runtime10.jsxs(Text, {
    children: [
      /* @__PURE__ */ jsx_runtime10.jsx(Text, {
        color: palette.accent,
        children: "▎"
      }),
      /* @__PURE__ */ jsx_runtime10.jsxs(Text, {
        bold: true,
        color: palette.accent,
        children: [
          " ",
          label
        ]
      })
    ]
  });
}
function elideTail(s, max2) {
  if (max2 <= 1)
    return s.slice(0, Math.max(1, max2));
  if (s.length <= max2)
    return s;
  return s.slice(0, max2 - 1) + "…";
}
function elideMiddle(s, max2) {
  if (max2 <= 1)
    return s.slice(0, Math.max(1, max2));
  if (s.length <= max2)
    return s;
  const keep = max2 - 1;
  const left = Math.floor(keep / 2);
  const right = keep - left;
  return s.slice(0, left) + "…" + s.slice(-right);
}

// src/components/Owl.tsx
var import_react24 = __toESM(require_react(), 1);
var jsx_runtime11 = __toESM(require_jsx_runtime(), 1);
var INK_WEIGHT = {
  " ": 0,
  ".": 1,
  ",": 1,
  ":": 2,
  ";": 2,
  "-": 3,
  "=": 4,
  "+": 4,
  "*": 6,
  "%": 7,
  "#": 8,
  "@": 9
};
function tone(ch) {
  if (ch === " ")
    return "blank";
  if ("#@%*:;-.,".includes(ch))
    return "body";
  return "field";
}
function downscaleArt(rows, maxW, maxH) {
  if (rows.length === 0 || maxW <= 0 || maxH <= 0)
    return rows;
  const srcH = rows.length;
  const srcW = Math.max(...rows.map((r) => r.length));
  if (srcW <= maxW && srcH <= maxH)
    return rows;
  const s = Math.max(srcW / maxW, srcH / maxH);
  const newW = Math.max(1, Math.floor(srcW / s));
  const newH = Math.max(1, Math.floor(srcH / s));
  const out = [];
  for (let y = 0;y < newH; y++) {
    const y0 = Math.floor(y * s);
    const y1 = Math.max(y0 + 1, Math.floor((y + 1) * s));
    let line = "";
    for (let x = 0;x < newW; x++) {
      const x0 = Math.floor(x * s);
      const x1 = Math.max(x0 + 1, Math.floor((x + 1) * s));
      line += pickRepresentative(rows, y0, y1, x0, x1, srcH, srcW);
    }
    out.push(line);
  }
  return out;
}
function pickRepresentative(rows, y0, y1, x0, x1, srcH, srcW) {
  let best = " ";
  let bestWeight = -1;
  for (let sy = y0;sy < Math.min(y1, srcH); sy++) {
    const row = rows[sy] ?? "";
    for (let sx = x0;sx < Math.min(x1, srcW); sx++) {
      const ch = row[sx] ?? " ";
      const w = INK_WEIGHT[ch] ?? 5;
      if (w > bestWeight) {
        best = ch;
        bestWeight = w;
      }
    }
  }
  return best;
}
function OwlPanel({
  palette,
  width,
  height,
  children
}) {
  return /* @__PURE__ */ jsx_runtime11.jsx(Box_default, {
    borderStyle: "round",
    borderColor: palette.primary_faint,
    flexDirection: "column",
    paddingX: 1,
    ...width ? { width } : { flexGrow: 1 },
    alignItems: "center",
    ...height ? { height } : {},
    children
  });
}
function PhotoOwl({
  pixels,
  palette,
  width,
  height
}) {
  const lines = pixels.cells.map((row, rowIdx) => {
    const cells = row.map((tuple, colIdx) => {
      const glyph = tuple[0] ?? " ";
      const fg = tuple[1] ?? "#000000";
      const bg = tuple[2] ?? fg;
      return /* @__PURE__ */ jsx_runtime11.jsx(Text, {
        color: fg,
        backgroundColor: bg,
        children: glyph
      }, colIdx);
    });
    return /* @__PURE__ */ jsx_runtime11.jsx(Box_default, {
      children: cells
    }, rowIdx);
  });
  const panelOuterW = pixels.width + 4;
  return /* @__PURE__ */ jsx_runtime11.jsx(OwlPanel, {
    palette,
    width: panelOuterW,
    height,
    children: lines
  });
}
function AsciiOwl({
  art,
  palette,
  width,
  maxHeight,
  height
}) {
  const innerW = Math.max(1, width - 4);
  const innerH = Math.max(1, maxHeight - 2);
  const rendered = import_react24.useMemo(() => downscaleArt(art, innerW, innerH), [art, innerW, innerH]);
  if (rendered.length === 0)
    return null;
  const lines = rendered.map((row, rowIdx) => {
    const spans = [];
    let runStart = 0;
    let runTone = tone(row[0] ?? " ");
    for (let i = 1;i <= row.length; i++) {
      const t = i < row.length ? tone(row[i] ?? " ") : null;
      if (t !== runTone) {
        const segment = row.slice(runStart, i);
        spans.push(renderSpan(segment, runTone, palette, `${rowIdx}-${runStart}`));
        runStart = i;
        if (t !== null)
          runTone = t;
      }
    }
    return /* @__PURE__ */ jsx_runtime11.jsx(Box_default, {
      children: spans
    }, rowIdx);
  });
  return /* @__PURE__ */ jsx_runtime11.jsx(OwlPanel, {
    palette,
    height,
    children: lines
  });
}
function renderSpan(segment, segTone, palette, key) {
  if (segTone === "blank") {
    return /* @__PURE__ */ jsx_runtime11.jsx(Text, {
      children: segment
    }, key);
  }
  const color = segTone === "body" ? palette.accent : palette.primary_faint;
  return /* @__PURE__ */ jsx_runtime11.jsx(Text, {
    color,
    children: segment
  }, key);
}
function Owl({
  art,
  pixels,
  palette,
  width,
  maxHeight,
  height
}) {
  if (pixels && pixels.cells.length > 0) {
    return /* @__PURE__ */ jsx_runtime11.jsx(PhotoOwl, {
      pixels,
      palette,
      width,
      height
    });
  }
  return /* @__PURE__ */ jsx_runtime11.jsx(AsciiOwl, {
    art,
    palette,
    width,
    maxHeight,
    height
  });
}

// src/components/Wordmark.tsx
var jsx_runtime12 = __toESM(require_jsx_runtime(), 1);
var _LETTER_A = [
  " ┏━━━┓ ",
  " ┃░░░┃ ",
  " ┃░░░┃ ",
  " ┣━━━┫ ",
  " ┃░░░┃ ",
  " ╹░░░╹ "
];
var _LETTER_T = [
  "━━━━━━━",
  "░░░╻░░░",
  "░░░┃░░░",
  "░░░┃░░░",
  "░░░┃░░░",
  "░░░╹░░░"
];
var _LETTER_H = [
  " ╻░░░╻ ",
  " ┃░░░┃ ",
  " ┃░░░┃ ",
  " ┣━━━┫ ",
  " ┃░░░┃ ",
  " ╹░░░╹ "
];
var _LETTER_E = [
  " ┏━━━┓ ",
  " ┃░░░╹ ",
  " ┣━━━╸ ",
  " ┃░░░░ ",
  " ┃░░░╻ ",
  " ┗━━━┛ "
];
var _LETTER_N = [
  " ╻░░░╻ ",
  " ┃╲░░┃ ",
  " ┃░╲░┃ ",
  " ┃░░╲┃ ",
  " ┃░░░┃ ",
  " ╹░░░╹ "
];
var _WORDMARK_LETTERS = [_LETTER_A, _LETTER_T, _LETTER_H, _LETTER_E, _LETTER_N, _LETTER_A];
var WORDMARK_ROWS = Array.from({ length: 6 }, (_, rowIdx) => _WORDMARK_LETTERS.map((letter) => letter[rowIdx] ?? "").join(" "));
var BREAKPOINT_WIDE = 56;
var BREAKPOINT_MEDIUM = 26;
function Wordmark({
  palette,
  termCols
}) {
  if (termCols >= BREAKPOINT_WIDE)
    return /* @__PURE__ */ jsx_runtime12.jsx(WordmarkFull, {
      palette
    });
  if (termCols >= BREAKPOINT_MEDIUM)
    return /* @__PURE__ */ jsx_runtime12.jsx(WordmarkMedium, {
      palette
    });
  return /* @__PURE__ */ jsx_runtime12.jsx(WordmarkNarrow, {
    palette
  });
}
var SHADOW_GLYPHS = new Set([
  "░"
]);
var LETTER_RANGES = [
  [0, 7],
  [8, 15],
  [16, 23],
  [24, 31],
  [32, 39],
  [40, 47]
];
function _letterAt(col) {
  for (let i = 0;i < LETTER_RANGES.length; i++) {
    const range2 = LETTER_RANGES[i];
    if (!range2)
      continue;
    const [start, end] = range2;
    if (col >= start && col < end)
      return i;
  }
  return -1;
}
function _segmentRow(row) {
  const out = [];
  let cur = "";
  let curKind = null;
  let curLetter = null;
  for (let i = 0;i < row.length; i++) {
    const ch = row[i] ?? " ";
    const kind = ch === " " ? "space" : SHADOW_GLYPHS.has(ch) ? "shadow" : "block";
    const letterIdx = _letterAt(i);
    if (cur && (kind !== curKind || letterIdx !== curLetter)) {
      out.push({ text: cur, kind: curKind, letterIdx: curLetter });
      cur = "";
    }
    cur += ch;
    curKind = kind;
    curLetter = letterIdx;
  }
  if (cur) {
    out.push({ text: cur, kind: curKind, letterIdx: curLetter });
  }
  return out;
}
function WordmarkFull({ palette }) {
  const tick = useTicker(500);
  const gradient = palette.gradient && palette.gradient.length >= 3 ? palette.gradient : [
    palette.accent,
    palette.primary,
    palette.primary_dim,
    palette.primary,
    palette.accent
  ];
  const blockColor = (letterIdx) => {
    if (letterIdx < 0)
      return palette.accent;
    const idx = (letterIdx + tick) % gradient.length;
    return gradient[idx] ?? palette.accent;
  };
  const shadowColor = palette.primary_faint || palette.primary_dim;
  return /* @__PURE__ */ jsx_runtime12.jsx(Box_default, {
    flexDirection: "column",
    alignItems: "center",
    children: WORDMARK_ROWS.map((row, rowIdx) => {
      const segs = _segmentRow(row);
      return /* @__PURE__ */ jsx_runtime12.jsx(Text, {
        children: segs.map((s, j) => {
          if (s.kind === "space") {
            return /* @__PURE__ */ jsx_runtime12.jsx(Text, {
              children: s.text
            }, j);
          }
          if (s.kind === "shadow") {
            return /* @__PURE__ */ jsx_runtime12.jsx(Text, {
              color: shadowColor,
              children: s.text
            }, j);
          }
          return /* @__PURE__ */ jsx_runtime12.jsx(Text, {
            bold: true,
            color: blockColor(s.letterIdx),
            children: s.text
          }, j);
        })
      }, rowIdx);
    })
  });
}
function WordmarkMedium({ palette }) {
  return /* @__PURE__ */ jsx_runtime12.jsx(Box_default, {
    justifyContent: "center",
    children: /* @__PURE__ */ jsx_runtime12.jsxs(Text, {
      bold: true,
      color: palette.accent,
      children: [
        "▰▰",
        "  ",
        "A T H E N A",
        "  ",
        "▰▰"
      ]
    })
  });
}
function WordmarkNarrow({ palette }) {
  return /* @__PURE__ */ jsx_runtime12.jsx(Box_default, {
    justifyContent: "center",
    children: /* @__PURE__ */ jsx_runtime12.jsx(Text, {
      bold: true,
      color: palette.accent,
      children: "athena"
    })
  });
}

// src/components/Banner.tsx
var jsx_runtime13 = __toESM(require_jsx_runtime(), 1);
var SPRAY_CAP = "▒▒";
var SPRAY_FILL_MAX = 46;
var SPRAY_FILL_MIN = 12;
var MIN_OWL_WIDTH = 32;
var PANEL_HEIGHT_FALLBACK = 22;
function _Banner({
  event,
  termCols,
  termRows
}) {
  const palette = event.palette ?? defaultPalette();
  const sideBySide = termCols >= MIN_OWL_WIDTH * 2 + 4 && event.owl_pixels !== null;
  const panelHeight = Math.max(PANEL_HEIGHT_FALLBACK, event.owl_pixels ? event.owl_pixels.height + 2 : PANEL_HEIGHT_FALLBACK);
  const OUTER_PADDING = 2;
  const GAP = 1;
  const owlPanelOuterW = sideBySide && event.owl_pixels ? event.owl_pixels.width + 4 : 0;
  const infoPanelOuterW = sideBySide ? Math.max(30, termCols - owlPanelOuterW - GAP - OUTER_PADDING) : Math.max(30, termCols - OUTER_PADDING);
  return /* @__PURE__ */ jsx_runtime13.jsxs(Box_default, {
    flexDirection: "column",
    children: [
      /* @__PURE__ */ jsx_runtime13.jsx(Wordmark, {
        palette,
        termCols
      }),
      /* @__PURE__ */ jsx_runtime13.jsx(Box_default, {
        alignItems: "center",
        justifyContent: "center",
        children: /* @__PURE__ */ jsx_runtime13.jsxs(Text, {
          children: [
            /* @__PURE__ */ jsx_runtime13.jsx(Text, {
              color: palette.primary_faint,
              children: SPRAY_CAP
            }),
            /* @__PURE__ */ jsx_runtime13.jsx(Text, {
              color: palette.primary,
              children: "█".repeat(Math.max(SPRAY_FILL_MIN, Math.min(SPRAY_FILL_MAX, termCols - 8)))
            }),
            /* @__PURE__ */ jsx_runtime13.jsx(Text, {
              color: palette.primary_faint,
              children: SPRAY_CAP
            })
          ]
        })
      }),
      /* @__PURE__ */ jsx_runtime13.jsxs(Box_default, {
        marginTop: 1,
        flexDirection: "row",
        gap: 1,
        alignItems: "flex-start",
        children: [
          sideBySide && /* @__PURE__ */ jsx_runtime13.jsx(Owl, {
            art: event.owl_art,
            pixels: event.owl_pixels,
            palette,
            width: Math.floor((termCols - 4) / 2),
            maxHeight: panelHeight,
            height: panelHeight
          }),
          /* @__PURE__ */ jsx_runtime13.jsx(InfoPanel, {
            model: event.model,
            cwd: event.cwd,
            themeName: palette.name,
            themeDescription: palette.description,
            tools: event.tools,
            commandsHint: event.commands_hint,
            palette,
            height: panelHeight,
            width: infoPanelOuterW
          })
        ]
      })
    ]
  });
}
function defaultPalette() {
  return {
    name: "phosphor",
    description: "fallback",
    primary: "green",
    primary_dim: "green",
    primary_faint: "green",
    accent: "yellow",
    accent_dim: "yellow",
    gradient: []
  };
}
var Banner = import_react25.default.memo(_Banner);

// src/components/Nameplate.tsx
var jsx_runtime14 = __toESM(require_jsx_runtime(), 1);
function Nameplate({
  banner,
  palette
}) {
  return /* @__PURE__ */ jsx_runtime14.jsxs(Box_default, {
    children: [
      /* @__PURE__ */ jsx_runtime14.jsx(Text, {
        bold: true,
        color: palette.primary,
        children: "██ athena"
      }),
      /* @__PURE__ */ jsx_runtime14.jsx(Text, {
        color: palette.primary_dim,
        children: " · "
      }),
      /* @__PURE__ */ jsx_runtime14.jsx(Text, {
        color: palette.accent,
        children: banner.model
      }),
      /* @__PURE__ */ jsx_runtime14.jsx(Text, {
        color: palette.primary_dim,
        children: " · "
      }),
      /* @__PURE__ */ jsx_runtime14.jsx(Text, {
        color: palette.primary,
        children: palette.name
      })
    ]
  });
}

// src/components/PulsingCursor.tsx
var jsx_runtime15 = __toESM(require_jsx_runtime(), 1);
function PulsingCursor({
  lastDeltaAtMs,
  solidWindowMs = 400,
  color
}) {
  const tick = useTicker(250);
  if (lastDeltaAtMs === null)
    return null;
  const ageMs = performance.now() - lastDeltaAtMs;
  if (ageMs < solidWindowMs) {
    return /* @__PURE__ */ jsx_runtime15.jsx(Text, {
      color,
      children: "▌"
    });
  }
  const visible = tick % 2 === 0;
  return /* @__PURE__ */ jsx_runtime15.jsx(Text, {
    color,
    children: visible ? "▌" : " "
  });
}

// src/stream/inlineMarkdown.ts
function parseInline(text) {
  if (!text)
    return [];
  const out = [];
  let i = 0;
  let buf = "";
  const flush = () => {
    if (buf) {
      out.push({ text: buf });
      buf = "";
    }
  };
  const push = (seg) => {
    if (seg.text)
      out.push(seg);
  };
  while (i < text.length) {
    const ch = text[i];
    if (ch === "`") {
      const end = text.indexOf("`", i + 1);
      if (end > i) {
        flush();
        push({ text: text.slice(i + 1, end), code: true });
        i = end + 1;
        continue;
      }
    }
    if (ch === "*" && text[i + 1] === "*") {
      const end = text.indexOf("**", i + 2);
      if (end > i + 1) {
        flush();
        push({ text: text.slice(i + 2, end), bold: true });
        i = end + 2;
        continue;
      }
      buf += "**";
      i += 2;
      continue;
    }
    if (ch === "*") {
      const end = text.indexOf("*", i + 1);
      if (end > i && text[end + 1] !== "*" && text[end - 1] !== "*") {
        flush();
        push({ text: text.slice(i + 1, end), italic: true });
        i = end + 1;
        continue;
      }
    }
    if (text.startsWith("http://", i) || text.startsWith("https://", i)) {
      let end = i;
      while (end < text.length && !/\s/.test(text[end]))
        end++;
      while (end > i + 8 && /[.,);:?!]$/.test(text[end - 1]))
        end--;
      flush();
      push({ text: text.slice(i, end), url: true });
      i = end;
      continue;
    }
    buf += ch;
    i++;
  }
  flush();
  return out;
}

// src/components/Transcript.tsx
var jsx_runtime16 = __toESM(require_jsx_runtime(), 1);
function Transcript({
  banner,
  lines,
  streaming,
  streamId,
  scrollOffset,
  visibleBudget,
  termCols,
  termRows,
  lastDeltaAtMs = null
}) {
  const palette = banner?.palette ?? undefined;
  const promptColor = palette?.primary ?? "green";
  const hasConversation = lines.length > 0 || streamId !== null;
  const headerHeight = hasConversation ? 1 : Math.max(15, termRows - 12);
  const rawRows = !scrollOffset && streamId !== null && streaming ? streaming.split(`
`) : [];
  let trimEnd2 = rawRows.length;
  while (trimEnd2 > 0 && rawRows[trimEnd2 - 1] === "")
    trimEnd2--;
  const streamingRows = rawRows.slice(0, trimEnd2);
  const streamReserve = streamingRows.length > 0 ? Math.min(streamingRows.length + 1, Math.floor(visibleBudget / 2)) : 0;
  const committedBudget = visibleBudget - streamReserve;
  const windowEnd = Math.max(0, lines.length - scrollOffset);
  const windowStart = Math.max(0, windowEnd - committedBudget);
  const visibleLines = hasConversation ? lines.slice(windowStart, windowEnd) : [];
  const moreBelow = scrollOffset > 0 ? scrollOffset : 0;
  const moreAbove = Math.max(0, windowStart);
  const scrolledUp = scrollOffset > 0;
  const streamTail = streamReserve > 0 ? streamingRows.slice(-streamReserve) : [];
  if (!hasConversation) {
    return /* @__PURE__ */ jsx_runtime16.jsxs(Box_default, {
      flexDirection: "column",
      flexGrow: 1,
      overflow: "hidden",
      children: [
        banner && palette ? /* @__PURE__ */ jsx_runtime16.jsx(Banner, {
          event: banner,
          termCols,
          termRows: headerHeight
        }) : /* @__PURE__ */ jsx_runtime16.jsx(Text, {
          dimColor: true,
          children: "connecting to gateway…"
        }),
        /* @__PURE__ */ jsx_runtime16.jsx(Box_default, {
          flexGrow: 1
        }),
        banner && palette && /* @__PURE__ */ jsx_runtime16.jsxs(Box_default, {
          flexDirection: "column",
          marginBottom: 1,
          paddingX: 2,
          children: [
            /* @__PURE__ */ jsx_runtime16.jsx(Text, {
              color: palette.primary_dim,
              children: "try one of these to get started:"
            }),
            /* @__PURE__ */ jsx_runtime16.jsxs(Box_default, {
              marginTop: 1,
              flexDirection: "column",
              children: [
                /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
                  color: palette.accent_dim,
                  children: [
                    "  ",
                    "explain what this project does"
                  ]
                }),
                /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
                  color: palette.accent_dim,
                  children: [
                    "  ",
                    "@ATHENA.md what should I know before touching the agent loop?"
                  ]
                }),
                /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
                  color: palette.accent_dim,
                  children: [
                    "  ",
                    "/plan refactor the X module"
                  ]
                }),
                /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
                  color: palette.accent_dim,
                  children: [
                    "  ",
                    "/help — list every slash command"
                  ]
                })
              ]
            }),
            /* @__PURE__ */ jsx_runtime16.jsxs(Box_default, {
              marginTop: 1,
              flexDirection: "column",
              alignItems: "center",
              children: [
                /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
                  color: palette.primary_faint,
                  children: [
                    "Enter sends · Shift+Enter newline · Tab completes",
                    " · ",
                    "↑↓ history · Ctrl+R search"
                  ]
                }),
                /* @__PURE__ */ jsx_runtime16.jsx(Text, {
                  color: palette.primary_faint,
                  children: "Shift+↑↓ or PageUp/Dn to scroll · Esc interrupt · Ctrl+C exit"
                })
              ]
            })
          ]
        })
      ]
    });
  }
  return /* @__PURE__ */ jsx_runtime16.jsxs(Box_default, {
    flexDirection: "column",
    flexGrow: 1,
    overflow: "hidden",
    children: [
      banner && palette && /* @__PURE__ */ jsx_runtime16.jsx(Nameplate, {
        banner,
        palette
      }),
      /* @__PURE__ */ jsx_runtime16.jsx(Box_default, {
        flexGrow: 1
      }),
      moreAbove > 0 && /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
        color: palette?.primary_faint ?? "gray",
        dimColor: true,
        children: [
          "↑ ",
          moreAbove,
          " earlier line",
          moreAbove === 1 ? "" : "s",
          scrollOffset === 0 ? " — Shift+↑ or PageUp to scroll" : ""
        ]
      }),
      visibleLines.map((line) => renderLine(line, palette, promptColor)),
      streamTail.length > 0 && /* @__PURE__ */ jsx_runtime16.jsxs(jsx_runtime16.Fragment, {
        children: [
          streamTail.map((row, i) => /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
            color: "white",
            children: [
              i === 0 ? "" : "   ",
              i === 0 ? "" : "",
              row
            ]
          }, `s${i}`)),
          /* @__PURE__ */ jsx_runtime16.jsx(PulsingCursor, {
            lastDeltaAtMs,
            color: "white"
          })
        ]
      }),
      moreBelow > 0 && /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
        color: palette?.accent ?? "yellow",
        dimColor: true,
        children: [
          "↓ ",
          moreBelow,
          " newer line",
          moreBelow === 1 ? "" : "s",
          " — press Esc to jump to bottom"
        ]
      })
    ]
  });
}
function renderLine(line, palette, promptColor) {
  if (line.role === "separator") {
    return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
      color: palette?.primary_faint ?? "gray",
      children: line.content
    }, line.key);
  }
  if (line.role === "assistant") {
    const segments = parseInline(line.content);
    return /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
      color: "white",
      children: [
        "   ",
        segments.map((s, i) => {
          const segKey = `${line.key}-${i}`;
          if (s.code) {
            return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
              color: palette?.accent_dim ?? "yellow",
              children: s.text
            }, segKey);
          }
          if (s.url) {
            return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
              color: palette?.accent ?? "cyan",
              underline: true,
              children: s.text
            }, segKey);
          }
          return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
            bold: s.bold ?? false,
            italic: s.italic ?? false,
            children: s.text
          }, segKey);
        })
      ]
    }, line.key);
  }
  if (line.role === "tool") {
    const isHeader = line.content.startsWith("> ");
    return /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
      color: isHeader ? palette?.accent_dim ?? "yellow" : palette?.primary_dim ?? "gray",
      bold: isHeader,
      children: [
        "   ",
        line.content
      ]
    }, line.key);
  }
  if (line.role === "code") {
    return /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
      children: [
        /* @__PURE__ */ jsx_runtime16.jsx(Text, {
          color: palette?.accent_dim ?? "yellow",
          children: "   │ "
        }),
        /* @__PURE__ */ jsx_runtime16.jsx(Text, {
          color: palette?.accent ?? "cyan",
          children: line.content
        })
      ]
    }, line.key);
  }
  if (line.role === "diff-add") {
    return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
      color: "green",
      children: line.content
    }, line.key);
  }
  if (line.role === "diff-del") {
    return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
      color: "red",
      children: line.content
    }, line.key);
  }
  if (line.role === "diff-hunk") {
    return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
      color: palette?.accent_dim ?? "yellow",
      bold: true,
      children: line.content
    }, line.key);
  }
  if (line.role === "diff-file") {
    return /* @__PURE__ */ jsx_runtime16.jsx(Text, {
      color: palette?.primary_faint ?? "gray",
      bold: true,
      children: line.content
    }, line.key);
  }
  if (line.role === "user") {
    return /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
      color: promptColor,
      children: [
        "▸▸ ",
        line.content
      ]
    }, line.key);
  }
  return /* @__PURE__ */ jsx_runtime16.jsxs(Text, {
    color: palette?.primary_dim ?? "gray",
    children: [
      ".  ",
      line.content
    ]
  }, line.key);
}

// src/hooks/useInputHistory.ts
var import_react26 = __toESM(require_react(), 1);
function useInputHistory(maxEntries = 200) {
  const history = import_react26.useRef([]);
  const cursor = import_react26.useRef(-1);
  const draft = import_react26.useRef("");
  const searchCursor = import_react26.useRef(-1);
  const searchQuery = import_react26.useRef("");
  const commit = import_react26.useCallback((text) => {
    if (!text)
      return;
    const last2 = history.current[history.current.length - 1];
    if (last2 !== text) {
      history.current.push(text);
      if (history.current.length > maxEntries) {
        history.current = history.current.slice(-maxEntries);
      }
    }
    cursor.current = -1;
    draft.current = "";
  }, [maxEntries]);
  const navigatePrev = import_react26.useCallback((currentDraft) => {
    const h = history.current;
    if (h.length === 0)
      return null;
    if (cursor.current === -1) {
      draft.current = currentDraft;
      cursor.current = h.length - 1;
      return h[cursor.current];
    }
    if (cursor.current === 0)
      return null;
    cursor.current -= 1;
    return h[cursor.current];
  }, []);
  const navigateNext = import_react26.useCallback(() => {
    const h = history.current;
    if (cursor.current === -1)
      return null;
    if (cursor.current >= h.length - 1) {
      cursor.current = -1;
      return draft.current;
    }
    cursor.current += 1;
    return h[cursor.current];
  }, []);
  const reset = import_react26.useCallback(() => {
    if (cursor.current !== -1) {
      cursor.current = -1;
      draft.current = "";
    }
    if (searchCursor.current !== -1) {
      searchCursor.current = -1;
      searchQuery.current = "";
    }
  }, []);
  const searchPrev = import_react26.useCallback((query, currentDraft) => {
    const h = history.current;
    if (h.length === 0 || !query)
      return null;
    const isContinuation = searchCursor.current !== -1 && searchQuery.current === query;
    if (!isContinuation) {
      if (cursor.current === -1) {
        draft.current = currentDraft;
      }
      searchQuery.current = query;
      searchCursor.current = h.length;
    }
    const q = query.toLowerCase();
    let i = searchCursor.current - 1;
    while (i >= 0) {
      if (h[i].toLowerCase().includes(q)) {
        searchCursor.current = i;
        return h[i];
      }
      i--;
    }
    searchCursor.current = 0;
    return null;
  }, []);
  const cancelSearch = import_react26.useCallback(() => {
    const restored = draft.current;
    searchCursor.current = -1;
    searchQuery.current = "";
    draft.current = "";
    return restored;
  }, []);
  const acceptSearch = import_react26.useCallback(() => {
    searchCursor.current = -1;
    searchQuery.current = "";
    draft.current = "";
  }, []);
  return {
    commit,
    navigatePrev,
    navigateNext,
    reset,
    searchPrev,
    cancelSearch,
    acceptSearch
  };
}

// src/hooks/useLineEditor.ts
var import_react27 = __toESM(require_react(), 1);
function useLineEditor() {
  const [text, setText] = import_react27.useState("");
  const [cursor, setCursor] = import_react27.useState(0);
  import_react27.useEffect(() => {
    if (cursor > text.length)
      setCursor(text.length);
  }, [text, cursor]);
  const insert = import_react27.useCallback((char) => {
    setText((s) => s.slice(0, cursor) + char + s.slice(cursor));
    setCursor((p) => p + char.length);
  }, [cursor]);
  const backspace = import_react27.useCallback(() => {
    if (cursor === 0)
      return;
    setText((s) => s.slice(0, cursor - 1) + s.slice(cursor));
    setCursor((p) => p - 1);
  }, [cursor]);
  const forwardDelete = import_react27.useCallback(() => {
    setText((s) => s.slice(0, cursor) + s.slice(cursor + 1));
  }, [cursor]);
  const moveLeft = import_react27.useCallback(() => {
    setCursor((p) => Math.max(0, p - 1));
  }, []);
  const moveRight = import_react27.useCallback(() => {
    setCursor((p) => Math.min(text.length, p + 1));
  }, [text.length]);
  const toStart = import_react27.useCallback(() => setCursor(0), []);
  const toEnd = import_react27.useCallback(() => setCursor(text.length), [text.length]);
  const killToStart = import_react27.useCallback(() => {
    setText((s) => s.slice(cursor));
    setCursor(0);
  }, [cursor]);
  const killToEnd = import_react27.useCallback(() => {
    setText((s) => s.slice(0, cursor));
  }, [cursor]);
  const killWordLeft = import_react27.useCallback(() => {
    setText((s) => {
      const left = s.slice(0, cursor);
      const right = s.slice(cursor);
      const trimmed = left.replace(/\s*\S+\s*$/, "");
      setCursor(trimmed.length);
      return trimmed + right;
    });
  }, [cursor]);
  const clear = import_react27.useCallback(() => {
    setText("");
    setCursor(0);
  }, []);
  return {
    text,
    cursor,
    insert,
    backspace,
    forwardDelete,
    moveLeft,
    moveRight,
    toStart,
    toEnd,
    killToStart,
    killToEnd,
    killWordLeft,
    clear
  };
}

// src/lib/workspaceFiles.ts
import * as fs2 from "node:fs";
import * as path from "node:path";
var EXCLUDED_DIRS = new Set([
  ".git",
  "node_modules",
  "__pycache__",
  "dist",
  "build",
  ".next",
  ".nuxt",
  ".cache",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".venv",
  "venv",
  "env",
  ".tox",
  "target",
  "out",
  ".idea",
  ".vscode",
  "ui-tui/dist",
  "athena/_tui_bundle"
]);
var EXCLUDED_EXTS = new Set([
  ".pyc",
  ".pyo",
  ".so",
  ".dll",
  ".exe",
  ".o",
  ".a",
  ".class",
  ".jar",
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".bmp",
  ".ico",
  ".webp",
  ".mp3",
  ".mp4",
  ".mov",
  ".avi",
  ".wav",
  ".zip",
  ".tar",
  ".gz",
  ".bz2",
  ".7z",
  ".lock"
]);
var MAX_FILES = 5000;
var MAX_DEPTH = 8;
var cache3 = null;
function ensureCache(root) {
  const now2 = Date.now();
  if (cache3 && cache3.root === root && now2 - cache3.builtAtMs < 60000) {
    return cache3.files;
  }
  const files = [];
  const walk = (dir, depth) => {
    if (files.length >= MAX_FILES)
      return;
    if (depth > MAX_DEPTH)
      return;
    let entries;
    try {
      entries = fs2.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      if (files.length >= MAX_FILES)
        return;
      const name = ent.name;
      if (name.startsWith(".") && name !== ".env" && name !== ".github") {
        if (EXCLUDED_DIRS.has(name))
          continue;
        if (ent.isDirectory())
          continue;
      }
      const full = path.join(dir, name);
      if (ent.isDirectory()) {
        if (EXCLUDED_DIRS.has(name))
          continue;
        walk(full, depth + 1);
      } else if (ent.isFile()) {
        const ext = path.extname(name).toLowerCase();
        if (EXCLUDED_EXTS.has(ext))
          continue;
        const rel = path.relative(root, full).split(path.sep).join("/");
        files.push(rel);
      }
    }
  };
  walk(root, 0);
  files.sort();
  cache3 = { root, files, builtAtMs: now2 };
  return files;
}
function matchWorkspaceFiles(root, query, limit = 10) {
  let all;
  try {
    all = ensureCache(root);
  } catch {
    return [];
  }
  if (!query)
    return all.slice(0, limit);
  const q = query.toLowerCase();
  const basenameStarts = [];
  const basenameContains = [];
  const pathContains = [];
  for (const f of all) {
    const lower = f.toLowerCase();
    const base2 = lower.split("/").pop() ?? lower;
    if (base2.startsWith(q))
      basenameStarts.push(f);
    else if (base2.includes(q))
      basenameContains.push(f);
    else if (lower.includes(q))
      pathContains.push(f);
    if (basenameStarts.length + basenameContains.length + pathContains.length >= limit * 3)
      break;
  }
  const merged = [...basenameStarts, ...basenameContains, ...pathContains];
  return merged.slice(0, limit);
}
function findActiveAtMention(text, cursorPos) {
  let i = cursorPos - 1;
  while (i >= 0) {
    const ch = text[i];
    if (ch === "@") {
      if (i === 0 || /\s/.test(text[i - 1])) {
        return { start: i, query: text.slice(i + 1, cursorPos) };
      }
      return null;
    }
    if (/\s/.test(ch))
      return null;
    i--;
  }
  return null;
}
function applyAtMentionCompletion(text, cursorPos, pickedPath) {
  const mention = findActiveAtMention(text, cursorPos);
  if (mention === null)
    return { text, cursor: cursorPos };
  const before2 = text.slice(0, mention.start);
  const after2 = text.slice(cursorPos);
  const replacement = "@" + pickedPath + " ";
  const newText = before2 + replacement + after2;
  const newCursor = before2.length + replacement.length;
  return { text: newText, cursor: newCursor };
}

// src/hooks/useBracketedPaste.ts
var import_react28 = __toESM(require_react(), 1);
var ENABLE = "\x1B[?2004h";
var DISABLE = "\x1B[?2004l";
var START_MARKER = "\x1B[200~";
var END_MARKER = "\x1B[201~";
function useBracketedPaste(onPaste, enabled = true) {
  const onPasteRef = import_react28.useRef(onPaste);
  onPasteRef.current = onPaste;
  import_react28.useEffect(() => {
    if (!enabled)
      return;
    const stdin = process.stdin;
    if (!stdin.isTTY)
      return;
    const origRead = stdin.read.bind(stdin);
    let pasteBuffer = "";
    let inPaste = false;
    stdin.read = function patchedRead(size2) {
      const chunk2 = origRead(size2);
      if (chunk2 === null)
        return null;
      const raw = typeof chunk2 === "string" ? chunk2 : chunk2.toString("utf-8");
      let out = "";
      let i = 0;
      while (i < raw.length) {
        if (!inPaste) {
          const startIdx = raw.indexOf(START_MARKER, i);
          if (startIdx === -1) {
            out += raw.slice(i);
            break;
          }
          out += raw.slice(i, startIdx);
          i = startIdx + START_MARKER.length;
          inPaste = true;
          pasteBuffer = "";
        } else {
          const endIdx = raw.indexOf(END_MARKER, i);
          if (endIdx === -1) {
            pasteBuffer += raw.slice(i);
            break;
          }
          pasteBuffer += raw.slice(i, endIdx);
          i = endIdx + END_MARKER.length;
          inPaste = false;
          try {
            onPasteRef.current(pasteBuffer);
          } catch (err) {
            console.error("paste handler threw:", err);
          }
          pasteBuffer = "";
        }
      }
      if (out.length === 0) {
        return origRead(0) ?? null;
      }
      return out;
    };
    process.stdout.write(ENABLE);
    return () => {
      process.stdout.write(DISABLE);
      stdin.read = origRead;
      pasteBuffer = "";
      inPaste = false;
    };
  }, [enabled]);
}

// src/hooks/useMouseWheel.ts
var import_react29 = __toESM(require_react(), 1);
var ENABLE2 = "\x1B[?1000h\x1B[?1006h";
var DISABLE2 = "\x1B[?1000l\x1B[?1006l";
var SGR_RE = /\x1b\[<(\d+);\d+;\d+[Mm]/g;
function useMouseWheel(onScroll, enabled = true) {
  const scrollRef = import_react29.useRef(onScroll);
  scrollRef.current = onScroll;
  import_react29.useEffect(() => {
    if (!enabled)
      return;
    const stdin = process.stdin;
    if (!stdin.isTTY)
      return;
    const origRead = stdin.read.bind(stdin);
    stdin.read = function patchedRead(size2) {
      const chunk2 = origRead(size2);
      if (chunk2 === null)
        return null;
      const str = typeof chunk2 === "string" ? chunk2 : chunk2.toString("utf-8");
      let m;
      SGR_RE.lastIndex = 0;
      while ((m = SGR_RE.exec(str)) !== null) {
        const btn = parseInt(m[1], 10);
        if ((btn & 67) === 64)
          scrollRef.current(3);
        else if ((btn & 67) === 65)
          scrollRef.current(-3);
      }
      const cleaned = str.replace(SGR_RE, "");
      if (cleaned.length === 0)
        return origRead(0) ?? null;
      return cleaned;
    };
    process.stdout.write(ENABLE2);
    return () => {
      process.stdout.write(DISABLE2);
      stdin.read = origRead;
    };
  }, [enabled]);
}

// src/hooks/useStdoutSize.ts
var import_react30 = __toESM(require_react(), 1);
var FALLBACK = { cols: 100, rows: 30 };
function readSize(stdout) {
  if (!stdout)
    return FALLBACK;
  const cols = stdout.columns;
  const rows = stdout.rows;
  return {
    cols: cols && cols > 0 ? cols : FALLBACK.cols,
    rows: rows && rows > 0 ? rows : FALLBACK.rows
  };
}
function useStdoutSize() {
  const { stdout } = use_stdout_default();
  const [size2, setSize] = import_react30.useState(() => readSize(stdout));
  import_react30.useEffect(() => {
    if (!stdout)
      return;
    const onResize = () => setSize(readSize(stdout));
    stdout.on("resize", onResize);
    onResize();
    return () => {
      stdout.off("resize", onResize);
    };
  }, [stdout]);
  return size2;
}

// src/stream/thinkBlocks.ts
var OPEN_TAG = "<think>";
var CLOSE_TAG = "</think>";
var LIVE_MARKER = "· thinking…";
var DONE_MARKER = "· (thought)";
var initialThinkFilterState = {
  inThink: false,
  tail: "",
  liveMarkerLen: 0
};
function partialPrefixSuffix(s, fromPos, tag) {
  const slice2 = s.slice(fromPos);
  const max2 = Math.min(slice2.length, tag.length - 1);
  for (let k = max2;k > 0; k--) {
    if (slice2.endsWith(tag.slice(0, k)))
      return k;
  }
  return 0;
}
function appendFilter(prev, chunk2) {
  const text = prev.tail + chunk2;
  let pos = 0;
  let inThink = prev.inThink;
  let append = "";
  let priorLiveMarkerLen = prev.liveMarkerLen;
  let appendLiveMarkerLen = 0;
  let popLen = 0;
  while (pos < text.length) {
    if (inThink) {
      const closeIdx = text.indexOf(CLOSE_TAG, pos);
      if (closeIdx === -1) {
        const tailLen = partialPrefixSuffix(text, pos, CLOSE_TAG);
        const tailStart = text.length - tailLen;
        const liveMarkerLen2 = priorLiveMarkerLen > 0 ? priorLiveMarkerLen : appendLiveMarkerLen;
        return {
          state: { inThink: true, tail: text.slice(tailStart), liveMarkerLen: liveMarkerLen2 },
          popLen,
          append
        };
      }
      if (priorLiveMarkerLen > 0) {
        popLen += priorLiveMarkerLen;
        priorLiveMarkerLen = 0;
      } else if (appendLiveMarkerLen > 0) {
        append = append.slice(0, -appendLiveMarkerLen);
        appendLiveMarkerLen = 0;
      }
      append += DONE_MARKER;
      inThink = false;
      pos = closeIdx + CLOSE_TAG.length;
    } else {
      const openIdx = text.indexOf(OPEN_TAG, pos);
      if (openIdx === -1) {
        const tailLen = partialPrefixSuffix(text, pos, OPEN_TAG);
        const tailStart = text.length - tailLen;
        append += text.slice(pos, tailStart);
        return {
          state: { inThink: false, tail: text.slice(tailStart), liveMarkerLen: 0 },
          popLen,
          append
        };
      }
      append += text.slice(pos, openIdx);
      append += LIVE_MARKER;
      appendLiveMarkerLen = LIVE_MARKER.length;
      inThink = true;
      pos = openIdx + OPEN_TAG.length;
    }
  }
  const liveMarkerLen = inThink ? priorLiveMarkerLen > 0 ? priorLiveMarkerLen : appendLiveMarkerLen : 0;
  return {
    state: { inThink, tail: "", liveMarkerLen },
    popLen,
    append
  };
}

// src/state/types.ts
var LINES_CAP = 5000;
var initialTuiState = {
  banner: null,
  status: null,
  protocolError: null,
  serverHello: null,
  lines: [],
  streaming: "",
  _streamFilter: initialThinkFilterState,
  streamId: null,
  toolLane: [],
  flash: null,
  confirmReq: null,
  askReq: null,
  scrollOffset: 0,
  _nextKey: 1,
  _lastProgressMs: 0,
  _pendingUserInputSince: null
};

// src/state/reducer.ts
function appendLine(lines, newLine) {
  if (lines.length < LINES_CAP)
    return [...lines, newLine];
  return [...lines.slice(lines.length - LINES_CAP + 1), newLine];
}
function appendLines(lines, newLines) {
  if (newLines.length === 0)
    return lines;
  const combined = [...lines, ...newLines];
  if (combined.length <= LINES_CAP)
    return combined;
  return combined.slice(combined.length - LINES_CAP);
}
function splitToRows(content, role, startKey) {
  if (role === "assistant") {
    return splitAssistantContent(content, startKey);
  }
  const parts = content.split(`
`);
  const rows = [];
  let key = startKey;
  for (const part of parts) {
    rows.push({ key, role, content: part });
    key++;
  }
  return { rows, nextKey: key };
}
function splitAssistantContent(content, startKey) {
  const parts = content.split(`
`);
  const rows = [];
  let key = startKey;
  let inFence = false;
  for (const part of parts) {
    const trimmed = part.trimStart();
    if (/^```+/.test(trimmed)) {
      inFence = !inFence;
      continue;
    }
    rows.push({
      key,
      role: inFence ? "code" : "assistant",
      content: part
    });
    key++;
  }
  return { rows, nextKey: key };
}
function splitDiffContent(content, startKey) {
  const parts = content.split(`
`);
  const rows = [];
  let key = startKey;
  for (const part of parts) {
    let role;
    if (part.startsWith("@@"))
      role = "diff-hunk";
    else if (part.startsWith("---") || part.startsWith("+++"))
      role = "diff-file";
    else if (part.startsWith("+"))
      role = "diff-add";
    else if (part.startsWith("-"))
      role = "diff-del";
    else
      role = "tool";
    rows.push({ key, role, content: part });
    key++;
  }
  return { rows, nextKey: key };
}
function nextKey(state) {
  return { key: state._nextKey, _nextKey: state._nextKey + 1 };
}
function reducer(state, action) {
  switch (action.type) {
    case "SET_PROTOCOL_ERROR":
      return { ...state, protocolError: action.event };
    case "SET_SERVER_HELLO":
      return { ...state, serverHello: action.event };
    case "APPEND_SEPARATOR": {
      const k = nextKey(state);
      return {
        ...state,
        lines: appendLine(state.lines, {
          key: k.key,
          role: "separator",
          content: action.content
        }),
        _nextKey: k._nextKey,
        scrollOffset: 0
      };
    }
    case "DISMISS_FLASH":
      return { ...state, flash: null };
    case "DISMISS_CONFIRM":
      return { ...state, confirmReq: null };
    case "DISMISS_ASK":
      return { ...state, askReq: null };
    case "SET_SCROLL": {
      const maxOffset = Math.max(0, state.lines.length);
      const clamped = Math.min(maxOffset, Math.max(0, action.offset));
      return { ...state, scrollOffset: clamped };
    }
    case "USER_INPUT_SENT":
      return {
        ...state,
        _pendingUserInputSince: performance.now(),
        _lastProgressMs: performance.now()
      };
    case "EVENT":
      return reduceEvent(state, action.event);
  }
}
function withProgress(state) {
  return {
    ...state,
    _lastProgressMs: performance.now(),
    _pendingUserInputSince: null
  };
}
function reduceEvent(state, event) {
  switch (event.type) {
    case "banner":
      return { ...state, banner: event };
    case "status":
      return { ...state, status: event };
    case "status.flash":
      return { ...state, flash: event };
    case "theme.change":
      return state.banner ? { ...state, banner: { ...state.banner, palette: event.palette } } : state;
    case "message.append": {
      const e = event;
      const wasAtBottom = state.scrollOffset === 0;
      const { rows, nextKey: nk } = splitToRows(e.content, e.role, state._nextKey);
      return withProgress({
        ...state,
        lines: appendLines(state.lines, rows),
        _nextKey: nk,
        scrollOffset: wasAtBottom ? 0 : state.scrollOffset
      });
    }
    case "stream.start": {
      const e = event;
      return withProgress({
        ...state,
        streamId: e.stream_id,
        streaming: "",
        _streamFilter: initialThinkFilterState
      });
    }
    case "stream.delta": {
      const e = event;
      if (e.stream_id !== state.streamId)
        return state;
      const { state: nextFilter, popLen, append } = appendFilter(state._streamFilter, e.text);
      const popped = popLen > 0 ? state.streaming.slice(0, state.streaming.length - popLen) : state.streaming;
      return withProgress({
        ...state,
        streaming: append ? popped + append : popped,
        _streamFilter: nextFilter
      });
    }
    case "stream.end": {
      const e = event;
      if (e.stream_id !== state.streamId)
        return state;
      const rawText = state.streaming + (state._streamFilter.tail || "");
      const finalText = rawText.replace(/·\s*\(thought\)\s*/g, "").trim();
      const hasContent = finalText.length > 0;
      const wasAtBottom = state.scrollOffset === 0;
      let newLines = state.lines;
      let nk = state._nextKey;
      if (hasContent) {
        const { rows, nextKey: nk2 } = splitToRows(finalText, "assistant", state._nextKey);
        newLines = appendLines(state.lines, rows);
        nk = nk2;
      }
      return withProgress({
        ...state,
        lines: newLines,
        _nextKey: nk,
        streaming: "",
        _streamFilter: initialThinkFilterState,
        streamId: null,
        scrollOffset: wasAtBottom ? 0 : state.scrollOffset
      });
    }
    case "tool.start": {
      const e = event;
      return withProgress({
        ...state,
        toolLane: [
          ...state.toolLane,
          {
            id: e.call_id,
            tool: e.tool,
            args: e.args_preview,
            startedAtMs: performance.now()
          }
        ]
      });
    }
    case "tool.complete": {
      const e = event;
      const wasAtBottom = state.scrollOffset === 0;
      const bodyText = truncate2(e.result_preview, 2000);
      const bodyLines = bodyText.split(`
`);
      const MAX_BODY = 12;
      const shown = bodyLines.slice(0, MAX_BODY);
      const overflow = bodyLines.length - MAX_BODY;
      const rows = [];
      let key = state._nextKey;
      rows.push({ key: key++, role: "tool", content: `> ${e.tool}` });
      const isDiff = e.tool.startsWith("diff ");
      if (isDiff) {
        const diffRows = splitDiffContent(shown.join(`
`), key);
        for (const r of diffRows.rows) {
          rows.push({ ...r, content: `  ${r.content}` });
        }
        key = diffRows.nextKey;
      } else {
        for (const line of shown) {
          rows.push({ key: key++, role: "tool", content: `  ${line}` });
        }
      }
      if (overflow > 0) {
        rows.push({ key: key++, role: "tool", content: `  ... (${overflow} more lines)` });
      }
      return withProgress({
        ...state,
        toolLane: state.toolLane.filter((t) => t.id !== e.call_id && t.tool !== e.tool),
        lines: appendLines(state.lines, rows),
        _nextKey: key,
        scrollOffset: wasAtBottom ? 0 : state.scrollOffset
      });
    }
    case "tool.progress":
      return withProgress(state);
    case "confirm.request":
      return { ...state, confirmReq: event, scrollOffset: 0 };
    case "ask_question.request":
      return {
        ...state,
        askReq: event,
        scrollOffset: 0
      };
    case "exit":
      return state;
    default:
      return state;
  }
}
function truncate2(s, max2) {
  if (s.length <= max2)
    return s;
  return s.slice(0, max2 - 1) + "…";
}

// src/transport/client.ts
import { connect } from "node:net";
function resolveTransport() {
  const sockPath = process.env["ATHENA_TUI_SOCK"];
  if (sockPath) {
    return { kind: "uds", options: { path: sockPath } };
  }
  const portRaw = process.env["ATHENA_TUI_PORT"];
  if (portRaw) {
    const port = Number.parseInt(portRaw, 10);
    if (!Number.isInteger(port) || port <= 0) {
      throw new Error(`ATHENA_TUI_PORT is not a valid port: ${portRaw}`);
    }
    return { kind: "tcp", options: { host: "127.0.0.1", port } };
  }
  throw new Error("neither ATHENA_TUI_SOCK nor ATHENA_TUI_PORT is set — " + "this binary must be launched by athena's tui_gateway");
}
var PROTOCOL_VERSION = 2;
var CLIENT_CAPABILITIES = ["heartbeats", "seq"];
function connectGateway() {
  const transport = resolveTransport();
  const handlers = new Set;
  const protocolErrorHandlers = new Set;
  let buffer = "";
  let closed = false;
  let helloSent = false;
  let serverHello = null;
  let lastSeq = 0;
  const socket = connect(transport.options);
  if (transport.kind === "tcp") {
    socket.setNoDelay(true);
  }
  function writeFrame(frame) {
    try {
      socket.write(JSON.stringify(frame) + `
`);
    } catch {}
  }
  function sendHello() {
    if (helloSent)
      return;
    helloSent = true;
    writeFrame({
      jsonrpc: "2.0",
      method: "hello",
      params: {
        protocol_version: PROTOCOL_VERSION,
        client_version: "tui-bundle",
        capabilities: CLIENT_CAPABILITIES,
        last_seq: 0
      }
    });
  }
  function sendPong() {
    writeFrame({
      jsonrpc: "2.0",
      method: "pong",
      params: {}
    });
  }
  socket.on("data", (chunk2) => {
    if (closed)
      return;
    buffer += chunk2.toString("utf-8");
    let nl = buffer.indexOf(`
`);
    while (nl !== -1) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) {
        dispatch(line);
      }
      nl = buffer.indexOf(`
`);
    }
  });
  socket.on("close", () => {
    if (closed)
      return;
    for (const h of handlers) {
      h({ type: "exit", reason: "gateway socket closed" });
    }
  });
  socket.on("error", () => {
    if (closed)
      return;
    for (const h of handlers) {
      h({ type: "exit", reason: "gateway socket error" });
    }
  });
  function dispatch(line) {
    let frame;
    try {
      frame = JSON.parse(line);
    } catch {
      return;
    }
    if (typeof frame !== "object" || frame === null)
      return;
    const fr = frame;
    if (typeof fr.method !== "string")
      return;
    if (typeof fr.seq === "number" && Number.isFinite(fr.seq)) {
      if (fr.seq > lastSeq) {
        lastSeq = fr.seq;
      }
    }
    const params = fr.params && typeof fr.params === "object" && !Array.isArray(fr.params) ? fr.params : {};
    const event = { ...params, type: fr.method };
    if (event.type === "hello") {
      const he = event;
      serverHello = he;
      if (he.protocol_version !== PROTOCOL_VERSION) {}
      sendHello();
      return;
    }
    if (event.type === "ping") {
      sendPong();
      return;
    }
    if (event.type === "protocol.error") {
      const pe = event;
      for (const h of protocolErrorHandlers) {
        h(pe);
      }
      return;
    }
    for (const h of handlers) {
      h(event);
    }
  }
  function sendCommand(cmd) {
    if (closed)
      return;
    const { type, ...params } = cmd;
    writeFrame({
      jsonrpc: "2.0",
      method: type,
      params
    });
  }
  function close() {
    if (closed)
      return;
    closed = true;
    handlers.clear();
    protocolErrorHandlers.clear();
    try {
      socket.end();
    } catch {}
  }
  function onEvent(handler) {
    handlers.add(handler);
    return () => handlers.delete(handler);
  }
  function onProtocolError(handler) {
    protocolErrorHandlers.add(handler);
    return () => protocolErrorHandlers.delete(handler);
  }
  function getLastSeq() {
    return lastSeq;
  }
  function getServerHello() {
    return serverHello;
  }
  return {
    onEvent,
    onProtocolError,
    sendCommand,
    getLastSeq,
    getServerHello,
    close
  };
}

// src/main.tsx
var jsx_runtime17 = __toESM(require_jsx_runtime(), 1);
function App2() {
  const { exit } = use_app_default();
  const { cols, rows } = useStdoutSize();
  const [state, dispatch] = import_react31.useReducer(reducer, initialTuiState);
  const editor = useLineEditor();
  const history = useInputHistory();
  const [client] = import_react31.useState(() => connectGateway());
  const [slashSelectedIdx, setSlashSelectedIdx] = import_react31.useState(0);
  const [reverseSearch, setReverseSearch] = import_react31.useState(null);
  const setEditorTo = (text) => {
    editor.clear();
    if (text)
      editor.insert(text);
  };
  const slashOpen = editor.text.startsWith("/");
  const slashMatches = slashOpen ? matchSlashCommands(editor.text) : [];
  const atMention = findActiveAtMention(editor.text, editor.cursor);
  const cwd2 = state.banner?.cwd ?? "";
  const atMatches = atMention !== null && cwd2 ? matchWorkspaceFiles(cwd2, atMention.query, 8) : [];
  const atOpen = atMention !== null && atMatches.length > 0;
  const [atSelectedIdx, setAtSelectedIdx] = import_react31.useState(0);
  const [askFocusedIdx, setAskFocusedIdx] = import_react31.useState(0);
  const [askSelections, setAskSelections] = import_react31.useState([]);
  const lastAskReqId = import_react31.useRef(null);
  if (state.askReq && state.askReq.request_id !== lastAskReqId.current) {
    lastAskReqId.current = state.askReq.request_id;
    setAskFocusedIdx(0);
    setAskSelections(state.askReq.questions.map((q) => q.multiSelect ? [] : null));
  } else if (!state.askReq && lastAskReqId.current !== null) {
    lastAskReqId.current = null;
  }
  const totalTokens = (state.status?.tokens_up ?? 0) + (state.status?.tokens_down ?? 0);
  const tokenRate = useTokenRate(totalTokens, { buckets: 16, windowSec: 30 });
  const flashQueue = import_react31.useRef([]);
  const flashTimer = import_react31.useRef(null);
  const FLASH_MIN_DWELL_MS = 800;
  const pumpFlashQueue = () => {
    if (flashTimer.current !== null)
      return;
    const next = flashQueue.current.shift();
    if (!next)
      return;
    const ttl = Math.max(FLASH_MIN_DWELL_MS, (next.ttl_seconds ?? 3) * 1000);
    flashTimer.current = setTimeout(() => {
      flashTimer.current = null;
      dispatch({ type: "DISMISS_FLASH" });
      pumpFlashQueue();
    }, ttl);
  };
  const lastDeltaAt = import_react31.useRef(null);
  import_react31.useEffect(() => {
    const unsub = client.onEvent((event) => {
      if (event.type === "exit") {
        unsub();
        process.exit(0);
      }
      if (event.type === "status.flash") {
        flashQueue.current.push(event);
        pumpFlashQueue();
      }
      if (event.type === "confirm.request") {
        process.stderr.write("\x07");
      }
      if (event.type === "stream.delta") {
        lastDeltaAt.current = performance.now();
      }
      if (event.type === "stream.end" || event.type === "stream.start") {
        lastDeltaAt.current = event.type === "stream.start" ? performance.now() : null;
      }
      dispatch({ type: "EVENT", event });
    });
    const unsubErr = client.onProtocolError((event) => {
      dispatch({ type: "SET_PROTOCOL_ERROR", event });
    });
    return () => {
      unsub();
      unsubErr();
    };
  }, [client]);
  const scrollOffsetRef = import_react31.useRef(state.scrollOffset);
  import_react31.useEffect(() => {
    scrollOffsetRef.current = state.scrollOffset;
  }, [state.scrollOffset]);
  const lastSentSize = import_react31.useRef(null);
  const resizeTimer = import_react31.useRef(null);
  import_react31.useEffect(() => {
    if (lastSentSize.current === null) {
      lastSentSize.current = { cols, rows };
      return;
    }
    if (lastSentSize.current.cols === cols && lastSentSize.current.rows === rows) {
      return;
    }
    if (resizeTimer.current !== null)
      clearTimeout(resizeTimer.current);
    resizeTimer.current = setTimeout(() => {
      resizeTimer.current = null;
      lastSentSize.current = { cols, rows };
      client.sendCommand({ type: "resize", cols, rows });
    }, 250);
    return () => {
      if (resizeTimer.current !== null) {
        clearTimeout(resizeTimer.current);
        resizeTimer.current = null;
      }
    };
  }, [cols, rows, client]);
  const mouseEnabled = process.platform !== "win32";
  const handleWheel = import_react31.useCallback((delta) => {
    dispatch({ type: "SET_SCROLL", offset: state.scrollOffset + delta });
  }, [state.scrollOffset]);
  useMouseWheel(handleWheel, mouseEnabled);
  useBracketedPaste((pasted) => {
    const normalized = pasted.replace(/\r\n/g, `
`).replace(/\r/g, `
`);
    history.reset();
    setSlashSelectedIdx(0);
    editor.insert(normalized);
  });
  use_input_default((typedChar, key) => {
    if (state.askReq) {
      const req = state.askReq;
      const qIdx = Math.min(askFocusedIdx, req.questions.length - 1);
      const focusedQ = req.questions[qIdx];
      const optCount = focusedQ.options.length + 1;
      const multi = !!focusedQ.multiSelect;
      if (key.escape) {
        client.sendCommand({
          type: "ask_question.reply",
          request_id: req.request_id,
          answers: [],
          cancelled: true
        });
        dispatch({ type: "DISMISS_ASK" });
        return;
      }
      if (key.return) {
        const answers = req.questions.map((q, i) => {
          const sel = askSelections[i];
          const q_text = q.question;
          if (sel === null || sel === undefined)
            return { question: q_text, answer: "(no answer)" };
          const labelFor = (idx) => {
            if (idx < q.options.length)
              return q.options[idx].label;
            return "Other";
          };
          if (Array.isArray(sel)) {
            if (sel.length === 0)
              return { question: q_text, answer: "(no answer)" };
            return { question: q_text, answer: sel.map(labelFor).join(", ") };
          }
          return { question: q_text, answer: labelFor(sel) };
        });
        client.sendCommand({
          type: "ask_question.reply",
          request_id: req.request_id,
          answers,
          cancelled: false
        });
        dispatch({ type: "DISMISS_ASK" });
        return;
      }
      if (key.tab) {
        setAskFocusedIdx((i) => (i + 1) % req.questions.length);
        return;
      }
      if (key.upArrow) {
        setAskSelections((prev) => {
          const next = [...prev];
          const cur = next[qIdx];
          if (multi) {
            return prev;
          }
          const curIdx = typeof cur === "number" ? cur : 0;
          next[qIdx] = (curIdx - 1 + optCount) % optCount;
          return next;
        });
        return;
      }
      if (key.downArrow) {
        setAskSelections((prev) => {
          const next = [...prev];
          const cur = next[qIdx];
          if (multi)
            return prev;
          const curIdx = typeof cur === "number" ? cur : -1;
          next[qIdx] = (curIdx + 1) % optCount;
          return next;
        });
        return;
      }
      if (multi && typedChar === " ") {
        return;
      }
      if (typedChar && /^[1-9]$/.test(typedChar)) {
        const n = parseInt(typedChar, 10) - 1;
        if (n < optCount) {
          setAskSelections((prev) => {
            const next = [...prev];
            const cur = next[qIdx];
            if (multi) {
              const arr = Array.isArray(cur) ? [...cur] : [];
              const at2 = arr.indexOf(n);
              if (at2 >= 0)
                arr.splice(at2, 1);
              else
                arr.push(n);
              next[qIdx] = arr;
            } else {
              next[qIdx] = n;
            }
            return next;
          });
        }
        return;
      }
      return;
    }
    if (state.confirmReq) {
      const ch = (typedChar || "").toLowerCase();
      let accepted = null;
      if (ch === "y")
        accepted = true;
      else if (ch === "n")
        accepted = false;
      else if (key.return)
        accepted = state.confirmReq.default;
      else if (key.escape)
        accepted = false;
      if (accepted !== null) {
        const req = state.confirmReq;
        client.sendCommand({
          type: "confirm.reply",
          request_id: req.request_id,
          accepted
        });
        dispatch({ type: "DISMISS_CONFIRM" });
      }
      return;
    }
    if (reverseSearch !== null) {
      if (key.escape) {
        const draftRestored = history.cancelSearch();
        setReverseSearch(null);
        editor.clear();
        if (draftRestored)
          editor.insert(draftRestored);
        return;
      }
      if (key.return) {
        const text = reverseSearch.match ?? reverseSearch.query;
        history.acceptSearch();
        setReverseSearch(null);
        editor.clear();
        if (text)
          editor.insert(text);
        return;
      }
      if (key.backspace || key.delete) {
        const newQuery = reverseSearch.query.slice(0, -1);
        if (!newQuery) {
          const draftRestored = history.cancelSearch();
          setReverseSearch(null);
          editor.clear();
          if (draftRestored)
            editor.insert(draftRestored);
          return;
        }
        const match = history.searchPrev(newQuery, editor.text);
        setReverseSearch({ query: newQuery, match });
        return;
      }
      if (typedChar && !key.ctrl && !key.meta) {
        const newQuery = reverseSearch.query + typedChar;
        const match = history.searchPrev(newQuery, editor.text);
        setReverseSearch({ query: newQuery, match });
        return;
      }
    }
    if (key.pageUp || key.ctrl && typedChar === "u" && editor.text === "") {
      const vb = computeVisibleBudget();
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset + vb });
      return;
    }
    if (key.pageDown) {
      const vb = computeVisibleBudget();
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset - vb });
      return;
    }
    if (key.shift && key.upArrow) {
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset + 1 });
      return;
    }
    if (key.shift && key.downArrow) {
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset - 1 });
      return;
    }
    if (key.tab && slashOpen && slashMatches.length > 0) {
      const pick2 = slashMatches[Math.min(slashSelectedIdx, slashMatches.length - 1)];
      setEditorTo(completionText(pick2));
      setSlashSelectedIdx(0);
      return;
    }
    if (key.tab && atOpen && atMention !== null) {
      const pick2 = atMatches[Math.min(atSelectedIdx, atMatches.length - 1)];
      const { text: nt, cursor: nc } = applyAtMentionCompletion(editor.text, editor.cursor, pick2);
      editor.clear();
      if (nt)
        editor.insert(nt);
      setAtSelectedIdx(0);
      return;
    }
    if (key.return) {
      if (key.shift) {
        editor.insert(`
`);
        history.reset();
        setSlashSelectedIdx(0);
        return;
      }
      if (editor.text.length > 0) {
        client.sendCommand({ type: "user.input", text: editor.text });
        dispatch({ type: "USER_INPUT_SENT" });
        dispatch({ type: "APPEND_SEPARATOR", content: turnSeparator() });
        history.commit(editor.text);
        editor.clear();
        setSlashSelectedIdx(0);
      }
      return;
    }
    if (key.upArrow) {
      if (slashOpen && slashMatches.length > 0) {
        setSlashSelectedIdx((i) => (i - 1 + slashMatches.length) % slashMatches.length);
        return;
      }
      if (atOpen) {
        setAtSelectedIdx((i) => (i - 1 + atMatches.length) % atMatches.length);
        return;
      }
      const recalled = history.navigatePrev(editor.text);
      if (recalled !== null)
        setEditorTo(recalled);
      return;
    }
    if (key.downArrow) {
      if (slashOpen && slashMatches.length > 0) {
        setSlashSelectedIdx((i) => (i + 1) % slashMatches.length);
        return;
      }
      if (atOpen) {
        setAtSelectedIdx((i) => (i + 1) % atMatches.length);
        return;
      }
      const recalled = history.navigateNext();
      if (recalled !== null)
        setEditorTo(recalled);
      return;
    }
    if (key.escape) {
      if (scrollOffsetRef.current > 0) {
        dispatch({ type: "SET_SCROLL", offset: 0 });
        return;
      }
      client.sendCommand({ type: "interrupt" });
      return;
    }
    if (key.ctrl && typedChar === "c") {
      client.sendCommand({ type: "interrupt" });
      exit();
      return;
    }
    if (key.ctrl && typedChar === "d" && editor.text === "") {
      client.sendCommand({ type: "interrupt" });
      exit();
      return;
    }
    if (key.leftArrow)
      return editor.moveLeft();
    if (key.rightArrow)
      return editor.moveRight();
    if (key.ctrl && typedChar === "a" || key.home) {
      return editor.toStart();
    }
    if (key.ctrl && typedChar === "e" || key.end) {
      return editor.toEnd();
    }
    if (key.ctrl && typedChar === "u")
      return editor.killToStart();
    if (key.ctrl && typedChar === "k")
      return editor.killToEnd();
    if (key.ctrl && typedChar === "w")
      return editor.killWordLeft();
    if (key.ctrl && typedChar === "r") {
      const q = reverseSearch?.query ?? editor.text;
      const match = history.searchPrev(q, editor.text);
      setReverseSearch({ query: q, match });
      return;
    }
    if (key.backspace || key.delete) {
      history.reset();
      return editor.backspace();
    }
    if (typedChar && !key.ctrl && !key.meta) {
      history.reset();
      setSlashSelectedIdx(0);
      setAtSelectedIdx(0);
      editor.insert(typedChar);
    }
  });
  function computeVisibleBudget() {
    const COMPOSER_BORDER = 2;
    let CONFIRM_EXTRA = 0;
    if (state.confirmReq) {
      CONFIRM_EXTRA = 1;
      if (state.confirmReq.tool_name)
        CONFIRM_EXTRA += 1;
      if (state.confirmReq.preview) {
        const previewLines = state.confirmReq.preview.split(`
`).length;
        CONFIRM_EXTRA += Math.min(previewLines, 15) + 2;
      }
    }
    const PLAN_MODE_BANNER = !state.confirmReq && state.status?.plan_mode ? 1 : 0;
    const EDITOR_LINES = state.confirmReq ? 0 : Math.max(0, editor.text.split(`
`).length - 1);
    const SLASH_POPUP_LINES = !state.confirmReq && editor.text.startsWith("/") ? Math.min(7, matchSlashCommands(editor.text).length) : 0;
    const AT_POPUP_LINES = !state.confirmReq && atOpen ? Math.min(8, atMatches.length) : 0;
    const base2 = 5 + COMPOSER_BORDER + CONFIRM_EXTRA + EDITOR_LINES + SLASH_POPUP_LINES + AT_POPUP_LINES + PLAN_MODE_BANNER;
    const reserved = base2 + (state.toolLane.length > 0 ? state.toolLane.length + 1 : 0);
    return Math.max(4, rows - reserved - 1);
  }
  const visibleBudget = computeVisibleBudget();
  return /* @__PURE__ */ jsx_runtime17.jsxs(Box_default, {
    flexDirection: "column",
    height: rows,
    paddingX: 1,
    children: [
      /* @__PURE__ */ jsx_runtime17.jsx(Transcript, {
        banner: state.banner,
        lines: state.lines,
        streaming: state.streaming,
        streamId: state.streamId,
        scrollOffset: state.scrollOffset,
        visibleBudget,
        termCols: cols,
        termRows: rows,
        lastDeltaAtMs: lastDeltaAt.current
      }),
      /* @__PURE__ */ jsx_runtime17.jsx(Composer, {
        banner: state.banner,
        status: state.status,
        toolLane: state.toolLane,
        flash: state.flash,
        confirmReq: state.confirmReq,
        inputText: editor.text,
        cursorPos: editor.cursor,
        tpsHistory: tokenRate.history,
        tpsCurrent: tokenRate.current,
        state,
        slashSelectedIdx,
        termCols: cols,
        atMatches,
        atSelectedIdx,
        reverseSearch,
        askFocusedIdx,
        askSelections
      })
    ]
  });
}
function turnSeparator() {
  const now2 = new Date;
  const hh = String(now2.getHours()).padStart(2, "0");
  const mm = String(now2.getMinutes()).padStart(2, "0");
  const ss = String(now2.getSeconds()).padStart(2, "0");
  return `── ${hh}:${mm}:${ss} ──`;
}
render_default(/* @__PURE__ */ jsx_runtime17.jsx(App2, {}));
