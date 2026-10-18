//#region node_modules/@lit/reactive-element/css-tag.js
/**
* @license
* Copyright 2019 Google LLC
* SPDX-License-Identifier: BSD-3-Clause
*/
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: ee, getOwnPropertySymbols: te, getPrototypeOf: ne } = Object, f = globalThis, re = f.trustedTypes, ie = re ? re.emptyScript : "", ae = f.reactiveElementPolyfillSupport, p = (e, t) => e, m = {
	toAttribute(e, t) {
		/**
		* @license
		* Copyright 2017 Google LLC
		* SPDX-License-Identifier: BSD-3-Clause
		*/
		switch (t) {
			case Boolean:
				e = e ? ie : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, oe = (e, t) => !l(e, t), se = {
	attribute: !0,
	type: String,
	converter: m,
	reflect: !1,
	useDefault: !1,
	hasChanged: oe
};
Symbol.metadata ??= Symbol("metadata"), f.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var h = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = se) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? se;
	}
	static _$Ei() {
		if (this.hasOwnProperty(p("elementProperties"))) return;
		let e = ne(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(p("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(p("properties"))) {
			let e = this.properties, t = [...ee(e), ...te(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? m : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? m : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? oe)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
h.elementStyles = [], h.shadowRootOptions = { mode: "open" }, h[p("elementProperties")] = /* @__PURE__ */ new Map(), h[p("finalized")] = /* @__PURE__ */ new Map(), ae?.({ ReactiveElement: h }), (f.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
/**
* @license
* Copyright 2017 Google LLC
* SPDX-License-Identifier: BSD-3-Clause
*/
var g = globalThis, _ = (e) => e, v = g.trustedTypes, ce = v ? v.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, le = "$lit$", y = `lit$${Math.random().toFixed(9).slice(2)}$`, ue = "?" + y, de = `<${ue}>`, b = document, x = () => b.createComment(""), S = (e) => e === null || typeof e != "object" && typeof e != "function", C = Array.isArray, fe = (e) => C(e) || typeof e?.[Symbol.iterator] == "function", w = "[ 	\n\f\r]", T = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, pe = /-->/g, me = />/g, E = RegExp(`>|${w}(?:([^\\s"'>=/]+)(${w}*=${w}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), he = /'/g, ge = /"/g, _e = /^(?:script|style|textarea|title)$/i, D = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), O = Symbol.for("lit-noChange"), k = Symbol.for("lit-nothing"), ve = /* @__PURE__ */ new WeakMap(), A = b.createTreeWalker(b, 129);
function ye(e, t) {
	if (!C(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return ce === void 0 ? t : ce.createHTML(t);
}
var be = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = T;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === T ? c[1] === "!--" ? o = pe : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = E) : (_e.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = E) : o = me : o === E ? c[0] === ">" ? (o = i ?? T, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? E : c[3] === "\"" ? ge : he) : o === ge || o === he ? o = E : o === pe || o === me ? o = T : (o = E, i = void 0);
		let d = o === E && e[t + 1].startsWith("/>") ? " " : "";
		a += o === T ? n + de : l >= 0 ? (r.push(s), n.slice(0, l) + le + n.slice(l) + y + d) : n + y + (l === -2 ? t : d);
	}
	return [ye(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, j = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = be(t, n);
		if (this.el = e.createElement(l, r), A.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = A.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(le)) {
					let t = u[o++], n = i.getAttribute(e).split(y), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? Se : r[1] === "?" ? Ce : r[1] === "@" ? we : P
					}), i.removeAttribute(e);
				} else e.startsWith(y) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (_e.test(i.tagName)) {
					let e = i.textContent.split(y), t = e.length - 1;
					if (t > 0) {
						i.textContent = v ? v.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], x()), A.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], x());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === ue) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(y, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += y.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = b.createElement("template");
		return n.innerHTML = e, n;
	}
};
function M(e, t, n = e, r) {
	if (t === O) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = S(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = M(e, i._$AS(e, t.values), i, r)), t;
}
var xe = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? b).importNode(t, !0);
		A.currentNode = r;
		let i = A.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new N(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new Te(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = A.nextNode(), a++);
		}
		return A.currentNode = b, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, N = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = k, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = M(this, e, t), S(e) ? e === k || e == null || e === "" ? (this._$AH !== k && this._$AR(), this._$AH = k) : e !== this._$AH && e !== O && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? fe(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== k && S(this._$AH) ? this._$AA.nextSibling.data = e : this.T(b.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = j.createElement(ye(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new xe(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = ve.get(e.strings);
		return t === void 0 && ve.set(e.strings, t = new j(e)), t;
	}
	k(t) {
		C(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(x()), this.O(x()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = _(e).nextSibling;
			_(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, P = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = k, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = k;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = M(this, e, t, 0), a = !S(e) || e !== this._$AH && e !== O, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = M(this, r[n + o], t, o), s === O && (s = this._$AH[o]), a ||= !S(s) || s !== this._$AH[o], s === k ? e = k : e !== k && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === k ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, Se = class extends P {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === k ? void 0 : e;
	}
}, Ce = class extends P {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== k);
	}
}, we = class extends P {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = M(this, e, t, 0) ?? k) === O) return;
		let n = this._$AH, r = e === k && n !== k || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== k && (n === k || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, Te = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		M(this, e);
	}
}, Ee = g.litHtmlPolyfillSupport;
Ee?.(j, N), (g.litHtmlVersions ??= []).push("3.3.3");
var De = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new N(t.insertBefore(x(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, F = globalThis, I = class extends h {
	constructor() {
		/**
		* @license
		* Copyright 2017 Google LLC
		* SPDX-License-Identifier: BSD-3-Clause
		*/
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = De(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return O;
	}
};
I._$litElement$ = !0, I.finalized = !0, F.litElementHydrateSupport?.({ LitElement: I });
var Oe = F.litElementPolyfillSupport;
Oe?.({ LitElement: I }), (F.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region src/api.ts
var L = "device_routines", ke = "sensor.device_routines_health", R = [
	"mon",
	"tue",
	"wed",
	"thu",
	"fri",
	"sat",
	"sun"
], Ae = [
	"every_day",
	"weekdays",
	"weekends",
	"some_days",
	"weekly_schedule"
], je = [
	"rebuild_index",
	"reinstall_blueprint",
	"clean_up_now",
	"refresh_summaries"
];
function z(e) {
	return typeof e == "object" && !!e && typeof e.code == "string" && typeof e.message == "string";
}
function B(e, t, n = {}) {
	return e.connection.sendMessagePromise({
		type: `${L}/${t}`,
		...n
	});
}
async function Me(e) {
	return (await B(e, "routines/list")).routines;
}
function Ne(e, t) {
	return B(e, "routines/get", { device_id: t });
}
function Pe(e, t, n) {
	return B(e, "routines/set", {
		device_id: t,
		settings: n
	});
}
function Fe(e, t, n, r) {
	return B(e, "routines/action", r === void 0 ? {
		action: t,
		target: n
	} : {
		action: t,
		target: n,
		until: r
	});
}
async function Ie(e, t) {
	return (await B(e, "devices/opt", { op: t })).devices;
}
async function Le(e, t, n) {
	return (await B(e, "devices/opt", {
		op: t,
		device_id: n
	})).results;
}
function Re(e, t) {
	return B(e, "schedule/today", t === void 0 ? {} : { date: t });
}
function ze(e) {
	return B(e, "settings/get");
}
function Be(e, t) {
	return B(e, "settings/set", { settings: t });
}
function Ve(e, t, n) {
	return B(e, "maintenance", {
		action: t,
		dry_run: n
	});
}
async function He(e) {
	return (await B(e, "conversions/list")).offers;
}
function Ue(e, t) {
	return B(e, "conversions/convert", { automation_entity_id: t });
}
function We(e, t) {
	return e.connection.subscribeMessage(t, { type: `${L}/subscribe` });
}
function V(e) {
	return `/config/devices/device/${encodeURIComponent(e)}`;
}
function H(e) {
	return `/config/automation/edit/${encodeURIComponent(e)}`;
}
var Ge = {
	panel: {
		title: "Device Routines",
		menu: "Open the sidebar",
		tabs: {
			routines: "Routines",
			today: "Today",
			settings: "Settings"
		}
	},
	common: {
		loading: "Loading",
		retry: "Try again",
		save: "Save",
		cancel: "Cancel",
		close: "Close",
		none: "None",
		no_area: "No area",
		error_unknown: "Something went wrong. Check the Home Assistant log and try again."
	},
	status: {
		active: "Active",
		paused: "Paused",
		skipping: "Skipping the next action",
		off: "Off",
		detached: "Detached",
		missing_target: "Target missing",
		invalid: "Settings need attention"
	},
	verb: {
		on: "On",
		off: "Off",
		toggle: "Toggle",
		start: "Start",
		dock: "Return to dock",
		pause: "Pause",
		stop: "Stop",
		open: "Open",
		close: "Close",
		lock: "Lock",
		unlock: "Unlock",
		unknown: "Not known yet"
	},
	kind: {
		routine: "Routine",
		automation: "Automation",
		detached_routine: "Detached routine"
	},
	days: {
		every_day: "Every day",
		weekdays: "Weekdays",
		weekends: "Weekends",
		some_days: "Some days",
		weekly_schedule: "Weekly schedule"
	},
	weekday: {
		mon: "Mon",
		tue: "Tue",
		wed: "Wed",
		thu: "Thu",
		fri: "Fri",
		sat: "Sat",
		sun: "Sun"
	},
	routines: {
		title: "Routines",
		empty: "No device has a routine yet. Opt a device in below, then set its times.",
		select_all: "Select every routine",
		select_row: "Select {device}",
		selection: "{count} selected",
		columns: {
			device: "Device",
			area: "Area",
			schedule: "Schedule",
			status: "Status",
			next_action: "Next action",
			pause: "Pause",
			actions: "Actions"
		},
		actions: {
			skip_next: "Skip next",
			pause: "Pause until",
			resume: "Resume",
			enable: "Enable",
			disable: "Disable",
			edit: "Edit settings",
			opt_out: "Opt out",
			confirm_opt_out: "Confirm opt out"
		},
		next_action: "{verb} {time}",
		no_next_action: "Nothing scheduled",
		no_sentence: "No schedule yet",
		paused_until_time: "Until {time}",
		not_paused: "Not paused",
		pause_until: "Paused until",
		pause_confirm: "Pause",
		open_automation: "Automation",
		result: "Routines changed: {count}.",
		ignored: "{target} was left out: {reason}",
		opted_out: "{device} is opted out. Its routine is off and is cleaned up after the clean up period.",
		edit: {
			title: "Settings of {device}",
			saved: "The settings of {device} are saved.",
			fields: {
				target_entity: "Routine controls",
				on_time: "Turn on at",
				off_time: "Turn off at",
				days: "Days",
				day_set: "On these days",
				schedule_entity: "Weekly schedule",
				turn_off_after_min: "Turn off after (minutes)",
				turn_back_on_after_min: "Turn back on after (minutes)",
				late_start_window_min: "Late start window (minutes)",
				catch_up: "Catch up after restart",
				respect_manual: "Respect manual changes",
				docked_guard: "Start only when docked"
			}
		},
		detached: {
			title: "Detached routines",
			description: "These routines were taken over in the automation editor and are normal automations now. Open the automation to change one."
		},
		opted_out_section: {
			title: "Opted out devices",
			description: "These devices were opted out. Their routines are off and keep their settings until the clean up period ends. Opt a device in again to keep its routine.",
			opt_in_again: "Opt in again"
		},
		conversions: {
			title: "Automations that can become routines",
			description: "These hand written automations do exactly what a routine does. Converting one creates the routine, turns the automation off and labels it Replaced by routine. Turning the automation back on undoes it.",
			automation: "Automation",
			convert: "Convert",
			confirm: "{alias} can become a routine on {device}.",
			original: "Now, as the automation",
			routine: "As a routine",
			confirm_convert: "Convert to a routine",
			converted: "{alias} is now a routine on {device}. The automation is off and labelled Replaced by routine."
		},
		devices: {
			title: "Add devices",
			description: "Devices with an entity a routine can drive. Suggested devices are already switched at set times by an automation.",
			load: "Show eligible devices",
			empty: "No device has an entity a routine can drive.",
			targets: "Entities",
			suggested: "Suggested",
			has_routine: "Has a routine",
			opt_in: "Opt in",
			opt_in_selected: "Opt in the selected devices",
			opted_in: "Devices opted in: {count}."
		}
	},
	today: {
		title: "Today",
		date: "Day",
		empty: "Nothing is scheduled on this day.",
		conflict: "Conflict",
		condition_one: "If 1 condition passes",
		condition_many: "If {count} conditions pass",
		columns: {
			time: "Time",
			device: "Device",
			action: "Action",
			source: "From"
		}
	},
	settings: {
		title: "Settings",
		description: "Defaults apply to routines created from now on; changing one never rewrites an existing routine. Saving reloads Device Routines.",
		saved: "Settings saved.",
		fields: {
			schedule_scope: {
				name: "Schedule sensor scope",
				description: "Which devices get a Schedule sensor: every device an automation acts on, only devices with a routine, or none."
			},
			time_format: {
				name: "Time format",
				description: "How times read in every sentence. Automatic follows the country set in Home Assistant."
			},
			default_catch_up: {
				name: "Catch up after a restart, for new routines",
				description: "After a restart, the device is put in the state its schedule expects."
			},
			default_respect_manual: {
				name: "Respect manual changes, for new routines",
				description: "A device someone switched by hand stays as it is until its next scheduled time."
			},
			default_late_start_window_min: {
				name: "Late start window in minutes, for new routines",
				description: "How long after a missed start time a new routine may still start its device. 0 turns late starts off."
			},
			cleanup_after_days: {
				name: "Clean up after, in days",
				description: "How long a routine and its helpers stay after their device is opted out or removed. 0 keeps them."
			},
			assign_area: {
				name: "Put routines in the device's area",
				description: "Give each routine automation the area of its device, so it shows on the area page."
			},
			on_removal: {
				name: "On removal",
				description: "What removing Device Routines does to the routine automations."
			},
			ai_task_entity: {
				name: "AI summary entity",
				description: "An AI Task entity id, or empty to keep AI summaries off. The options of Device Routines say what is sent to it."
			},
			ai_calls_per_hour: {
				name: "AI calls per hour",
				description: "The most summaries the AI summary entity writes in one hour."
			},
			offer_conversions: {
				name: "Offer to convert matching automations",
				description: "Offer, in Repairs, to turn a hand written automation that does exactly what a routine does into a routine."
			},
			raise_conflict_repairs: {
				name: "Raise Repairs issues for conflicts",
				description: "Raise a Repairs issue when a routine and another automation switch a device in opposite directions at the same minute."
			}
		},
		choices: {
			schedule_scope: {
				all: "All devices with automations",
				routines: "Only devices with routines",
				none: "Nowhere"
			},
			time_format: {
				auto: "Automatic",
				"12h": "12 hour (9:00 AM)",
				"24h": "24 hour (09:00)"
			},
			on_removal: {
				keep: "Keep them as normal automations",
				delete: "Delete them and their helpers"
			}
		},
		maintenance: {
			title: "Maintenance",
			description: "Every action is safe to run at any time. A preview shows what would change before anything does.",
			preview: "Preview",
			run_now: "Run now",
			would_change: "Items it would change: {count}",
			would_change_none: "Running it would change nothing.",
			changed: "Items changed: {count}",
			changed_none: "Nothing needed a change.",
			actions: {
				rebuild_index: {
					name: "Rebuild index",
					description: "Find every routine automation again from its markers and the registries."
				},
				reinstall_blueprint: {
					name: "Reinstall blueprint",
					description: "Put the shipped blueprint back when the installed file differs or is missing."
				},
				clean_up_now: {
					name: "Clean up now",
					description: "Remove the routine, helpers and controls of every opted out or removed device now, without waiting for the clean up period."
				},
				refresh_summaries: {
					name: "Refresh summaries",
					description: "Read every automation again and rewrite every Schedule summary."
				}
			}
		}
	},
	health: {
		title: "Health",
		missing: "The Health sensor of Device Routines is not available.",
		state: {
			ok: "OK",
			degraded: "Degraded",
			error: "Error"
		},
		attributes: {
			version: "Version",
			commit: "Commit",
			branch: "Branch",
			deployed_at: "Deployed at",
			channel: "Channel",
			blueprint_schema: "Blueprint schema",
			blueprint_status: "Blueprint",
			owned_count: "Routines owned",
			loaded_count: "Routines loaded",
			issues: "Open issues",
			ha_version: "Home Assistant",
			last_reconcile: "Last reconcile"
		}
	}
};
//#endregion
//#region src/localize.ts
function Ke(e, t = "", n = /* @__PURE__ */ new Map()) {
	for (let [r, i] of Object.entries(e)) {
		let e = t ? `${t}.${r}` : r;
		typeof i == "string" ? n.set(e, i) : Ke(i, e, n);
	}
	return n;
}
var U = { en: Ke(Ge) };
function qe(e) {
	let t = e?.locale?.language ?? e?.language ?? "en";
	return t in U ? t : t.split("-")[0] ?? "en";
}
function Je(e, t = {}) {
	return e.replace(/\{(\w+)\}/g, (e, n) => n in t ? String(t[n]) : e);
}
function W(e, t, n) {
	return Je((U[qe(e)] ?? U.en)?.get(t) ?? U.en?.get(t) ?? t, n);
}
var Ye = /* @__PURE__ */ new WeakMap();
async function Xe(e) {
	let t = Ye.get(e);
	t === void 0 && (t = e.loadBackendTranslation?.("exceptions", "device_routines") ?? Promise.resolve(void 0), Ye.set(e, t));
	try {
		return await t ?? e.localize;
	} catch {
		return e.localize;
	}
}
function Ze(e) {
	return z(e) ? e.translation_placeholders?.setting ?? void 0 : void 0;
}
async function G(e, t) {
	if (!z(t)) return W(e, "common.error_unknown");
	let n = await Xe(e), r = `component.${L}.exceptions.${t.code}.message`, i = n(r, t.translation_placeholders ?? {});
	return i && i !== r ? i : t.message || W(e, "common.error_unknown");
}
//#endregion
//#region src/navigate.ts
function Qe(e) {
	history.pushState(null, "", e), window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: !1 } }));
}
function K(e) {
	let t = e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;
	if (e.defaultPrevented || e.button !== 0 || t) return;
	let n = e.currentTarget;
	n instanceof HTMLAnchorElement && (e.preventDefault(), Qe(n.getAttribute("href") ?? "/"));
}
//#endregion
//#region src/styles.ts
var q = o`
  :host {
    display: block;
    color: var(--primary-text-color, #212121);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, sans-serif));
    font-size: var(--ha-font-size-m, 14px);
  }

  section {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--ha-card-border-radius, 12px);
    margin: 0 0 var(--ha-space-4, 16px);
    padding: var(--ha-space-4, 16px);
  }

  h2 {
    font-size: var(--ha-font-size-l, 16px);
    font-weight: var(--ha-font-weight-medium, 500);
    margin: 0 0 var(--ha-space-3, 12px);
  }

  p.hint {
    color: var(--secondary-text-color, #727272);
    margin: 0 0 var(--ha-space-3, 12px);
  }

  .scroll {
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    width: 100%;
  }

  th,
  td {
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    padding: var(--ha-space-2, 8px);
    text-align: start;
    vertical-align: top;
  }

  th {
    color: var(--secondary-text-color, #727272);
    font-weight: var(--ha-font-weight-medium, 500);
  }

  a {
    color: var(--primary-color, #03a9f4);
  }

  button {
    background: transparent;
    border: 1px solid var(--primary-color, #03a9f4);
    border-radius: var(--ha-border-radius-sm, 4px);
    color: var(--primary-color, #03a9f4);
    cursor: pointer;
    font: inherit;
    margin: 0 var(--ha-space-1, 4px) var(--ha-space-1, 4px) 0;
    padding: var(--ha-space-1, 4px) var(--ha-space-2, 8px);
  }

  button.primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }

  button:disabled {
    border-color: var(--disabled-text-color, #bdbdbd);
    color: var(--disabled-text-color, #bdbdbd);
    cursor: default;
  }

  input,
  select {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--ha-border-radius-sm, 4px);
    color: var(--primary-text-color, #212121);
    font: inherit;
    padding: var(--ha-space-1, 4px);
  }

  [aria-invalid="true"] {
    border-color: var(--error-color, #db4437);
    outline: 1px solid var(--error-color, #db4437);
  }

  .error {
    color: var(--error-color, #db4437);
    margin: var(--ha-space-2, 8px) 0;
  }

  .notice {
    color: var(--secondary-text-color, #727272);
    margin: var(--ha-space-2, 8px) 0;
  }

  .badge {
    border: 1px solid currentColor;
    border-radius: var(--ha-border-radius-pill, 999px);
    display: inline-block;
    font-size: var(--ha-font-size-s, 12px);
    margin-inline-start: var(--ha-space-1, 4px);
    padding: 0 var(--ha-space-2, 8px);
  }

  .muted {
    color: var(--secondary-text-color, #727272);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--ha-space-1, 4px);
    margin: 0 0 var(--ha-space-3, 12px);
  }

  .field.inline {
    align-items: center;
    flex-direction: row;
  }

  .field .description {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 12px);
  }
`, $e = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;
function et(e) {
	let t = $e.exec(e);
	if (t === null) return;
	let [n, r, i, a, o] = t.slice(1).map(Number);
	return new Date(Date.UTC(n, r - 1, i, a, o));
}
function tt(e, t = "auto") {
	if (t !== "auto") return t === "12h";
	switch (e?.locale?.time_format) {
		case "12": return !0;
		case "24": return !1;
		case "system": return new Intl.DateTimeFormat(void 0, { hour: "numeric" }).resolvedOptions().hour12;
		default: return;
	}
}
function nt(e, t, n) {
	let r = e?.locale?.language ?? e?.language ?? "en", i = tt(e, t);
	return new Intl.DateTimeFormat(r, {
		...n,
		...i === void 0 ? {} : { hour12: i },
		timeZone: "UTC"
	});
}
function rt(e, t, n) {
	let r = et(t);
	return r === void 0 ? t : nt(e, n, {
		hour: "numeric",
		minute: "2-digit"
	}).format(r);
}
function J(e, t, n) {
	let r = et(t);
	return r === void 0 ? t : nt(e, n, {
		weekday: "short",
		hour: "numeric",
		minute: "2-digit"
	}).format(r);
}
function Y(e, t) {
	return t === null ? W(e, "common.no_area") : e?.areas?.[t]?.name ?? t;
}
function X(e, t) {
	let n = e?.devices?.[t];
	return n?.name_by_user ?? n?.name ?? t;
}
function it(e) {
	return e === null ? "" : e.slice(0, 5);
}
//#endregion
//#region src/labels.ts
var at = {
	active: "status.active",
	paused: "status.paused",
	skipping: "status.skipping",
	off: "status.off",
	detached: "status.detached",
	missing_target: "status.missing_target",
	invalid: "status.invalid"
}, ot = {
	on: "verb.on",
	off: "verb.off",
	toggle: "verb.toggle",
	start: "verb.start",
	dock: "verb.dock",
	pause: "verb.pause",
	stop: "verb.stop",
	open: "verb.open",
	close: "verb.close",
	lock: "verb.lock",
	unlock: "verb.unlock"
}, st = {
	every_day: "days.every_day",
	weekdays: "days.weekdays",
	weekends: "days.weekends",
	some_days: "days.some_days",
	weekly_schedule: "days.weekly_schedule"
}, ct = {
	mon: "weekday.mon",
	tue: "weekday.tue",
	wed: "weekday.wed",
	thu: "weekday.thu",
	fri: "weekday.fri",
	sat: "weekday.sat",
	sun: "weekday.sun"
}, lt = {
	routine: "kind.routine",
	automation: "kind.automation",
	detached_routine: "kind.detached_routine"
};
function Z(e, t, n) {
	let r = t[n];
	return r === void 0 ? n : W(e, r);
}
function ut(e, t) {
	return Z(e, at, t);
}
function dt(e, t) {
	return t === null ? W(e, "verb.unknown") : Z(e, ot, t);
}
function ft(e, t) {
	return Z(e, lt, t);
}
//#endregion
//#region src/views/routines-view.ts
var pt = {
	skip_next: "routines.actions.skip_next",
	pause: "routines.actions.pause",
	resume: "routines.actions.resume",
	enable: "routines.actions.enable",
	disable: "routines.actions.disable"
}, mt = [
	"target_entity",
	"on_time",
	"off_time",
	"days",
	"day_set",
	"schedule_entity",
	"turn_off_after_min",
	"turn_back_on_after_min",
	"late_start_window_min",
	"catch_up",
	"respect_manual",
	"docked_guard"
], ht = {
	target_entity: "routines.edit.fields.target_entity",
	on_time: "routines.edit.fields.on_time",
	off_time: "routines.edit.fields.off_time",
	days: "routines.edit.fields.days",
	day_set: "routines.edit.fields.day_set",
	schedule_entity: "routines.edit.fields.schedule_entity",
	turn_off_after_min: "routines.edit.fields.turn_off_after_min",
	turn_back_on_after_min: "routines.edit.fields.turn_back_on_after_min",
	late_start_window_min: "routines.edit.fields.late_start_window_min",
	catch_up: "routines.edit.fields.catch_up",
	respect_manual: "routines.edit.fields.respect_manual",
	docked_guard: "routines.edit.fields.docked_guard"
};
function gt(e) {
	return {
		target_entity: e.target_entity,
		on_time: e.on_time,
		off_time: e.off_time,
		days: e.days,
		day_set: [...e.day_set],
		schedule_entity: e.schedule_entity,
		turn_off_after_min: e.turn_off_after_min,
		turn_back_on_after_min: e.turn_back_on_after_min,
		late_start_window_min: e.late_start_window_min,
		catch_up: e.catch_up,
		respect_manual: e.respect_manual,
		docked_guard: e.docked_guard
	};
}
function _t(e, t) {
	return e === "on_time" || e === "off_time" ? typeof t == "string" ? t.slice(0, 5) : "" : e === "day_set" && Array.isArray(t) ? R.filter((e) => t.includes(e)).join(",") : JSON.stringify(t);
}
function vt(e, t) {
	let n = {};
	for (let r of mt) _t(r, e[r]) !== _t(r, t[r]) && (n[r] = r === "day_set" ? R.filter((e) => t.day_set.includes(e)) : t[r]);
	return n;
}
function yt(e, t) {
	return e.device_name.localeCompare(t.device_name) || e.device_id.localeCompare(t.device_id);
}
function Q(e) {
	return e.opted_in === !1;
}
var bt = "unknown_command", xt = class extends I {
	static properties = {
		hass: { attribute: !1 },
		narrow: { type: Boolean },
		timeFormat: { attribute: !1 },
		_routines: { state: !0 },
		_error: { state: !0 },
		_notice: { state: !0 },
		_selected: { state: !0 },
		_pauseRow: { state: !0 },
		_pauseSelection: { state: !0 },
		_pauseUntil: { state: !0 },
		_editing: { state: !0 },
		_draft: { state: !0 },
		_editError: { state: !0 },
		_confirmOptOut: { state: !0 },
		_devices: { state: !0 },
		_suggested: { state: !0 },
		_devicesSelected: { state: !0 },
		_offers: { state: !0 },
		_offersError: { state: !0 },
		_confirmConvert: { state: !0 }
	};
	static styles = [q, o`
      .toolbar {
        align-items: center;
        display: flex;
        flex-wrap: wrap;
        gap: var(--ha-space-2, 8px);
        margin: 0 0 var(--ha-space-3, 12px);
      }

      .editor form {
        display: grid;
        gap: 0 var(--ha-space-4, 16px);
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      }

      .editor .wide {
        grid-column: 1 / -1;
      }

      fieldset {
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: var(--ha-border-radius-sm, 4px);
        margin: 0 0 var(--ha-space-3, 12px);
      }

      .sentences {
        display: grid;
        gap: var(--ha-space-2, 8px) var(--ha-space-4, 16px);
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        margin: 0 0 var(--ha-space-3, 12px);
      }

      .sentences strong {
        display: block;
        font-weight: var(--ha-font-weight-medium, 500);
      }
    `];
	_started = !1;
	constructor() {
		super(), this.narrow = !1, this._notice = [], this._selected = /* @__PURE__ */ new Set(), this._pauseSelection = !1, this._pauseUntil = "", this._suggested = /* @__PURE__ */ new Set(), this._devicesSelected = /* @__PURE__ */ new Set();
	}
	willUpdate(e) {
		e.has("hass") && this.hass !== void 0 && !this._started && (this._started = !0, this.refresh());
	}
	async refresh() {
		let e = this.hass;
		if (e === void 0) return;
		let t = this.refreshConversions();
		try {
			this._routines = await Me(e), this._error = void 0;
			let t = new Set(this._routines.filter((e) => !Q(e)).map((e) => e.device_id));
			this._selected = new Set([...this._selected].filter((e) => t.has(e)));
		} catch (t) {
			this._error = await G(e, t);
		}
		await t;
	}
	async refreshConversions() {
		let e = this.hass;
		if (e !== void 0) try {
			this._offers = await He(e), this._offersError = void 0;
		} catch (t) {
			this._offers = void 0, this._offersError = z(t) && t.code === bt ? void 0 : await G(e, t);
		}
	}
	async refreshRoutine(e) {
		let t = this.hass;
		if (t !== void 0 && this._routines !== void 0) try {
			let n = await Ne(t, e), r = this._routines.filter((t) => t.device_id !== e);
			this._routines = [...r, n].sort(yt);
		} catch (n) {
			z(n) && n.code === "not_opted_in" ? this._routines = this._routines.filter((t) => t.device_id !== e) : this._error = await G(t, n);
		}
	}
	_name(e) {
		return this._routines?.find((t) => t.device_id === e)?.device_name ?? this._devices?.find((t) => t.device_id === e)?.name ?? X(this.hass, e);
	}
	_ignoredName(e) {
		let t = e.placeholders ?? {}, n;
		if (e.kind === "area") n = this.hass?.areas?.[e.target]?.name;
		else if (e.kind === "device") {
			let t = this._name(e.target);
			n = t === e.target ? void 0 : t;
		}
		return t.device ?? n ?? t.target ?? e.target;
	}
	async _act(e, t, n) {
		let r = this.hass;
		if (r === void 0) return;
		let i;
		try {
			i = await Fe(r, e, { device_id: t }, n);
		} catch (e) {
			this._notice = [await G(r, e)];
			return;
		}
		this._pauseRow = void 0, this._pauseSelection = !1;
		let a = [W(r, "routines.result", { count: i.results.length })];
		for (let e of i.ignored) {
			let t = e.placeholders ?? {}, n = this._ignoredName(e), i = await G(r, {
				code: e.reason,
				message: e.reason,
				translation_placeholders: {
					device: n,
					target: n,
					...t
				}
			});
			a.push(W(r, "routines.ignored", {
				target: n,
				reason: i
			}));
		}
		this._notice = a, await this.refresh();
	}
	_actSelection(e) {
		if (e === "pause") {
			this._pauseSelection = !0, this._pauseRow = void 0;
			return;
		}
		this._act(e, [...this._selected]);
	}
	_actRow(e, t) {
		if (e === "pause") {
			this._pauseRow = t, this._pauseSelection = !1;
			return;
		}
		this._act(e, t);
	}
	_confirmPause(e) {
		this._pauseUntil !== "" && this._act("pause", e, this._pauseUntil);
	}
	async _optOut(e) {
		let t = this.hass;
		if (t !== void 0) {
			this._confirmOptOut = void 0;
			try {
				await Le(t, "out", [e]), this._notice = [W(t, "routines.opted_out", { device: this._name(e) })];
			} catch (e) {
				this._notice = [await G(t, e)];
			}
			await this.refresh();
		}
	}
	async _optIn(e) {
		let t = this.hass;
		if (t !== void 0 && e.length !== 0) {
			try {
				let n = await Le(t, "in", e);
				this._notice = [W(t, "routines.devices.opted_in", { count: n.length })], this._devicesSelected = /* @__PURE__ */ new Set();
			} catch (e) {
				this._notice = [await G(t, e)];
			}
			await this.refresh();
		}
	}
	async _loadDevices() {
		let e = this.hass;
		if (e !== void 0) try {
			let [t, n] = await Promise.all([Ie(e, "list"), Ie(e, "suggest")]);
			this._suggested = new Set(n.map((e) => e.device_id));
			let r = (e) => +!this._suggested.has(e.device_id);
			this._devices = [...t].sort((e, t) => r(e) - r(t));
		} catch (t) {
			this._notice = [await G(e, t)];
		}
	}
	async _convert(e) {
		let t = this.hass;
		if (t !== void 0) {
			this._confirmConvert = void 0;
			try {
				let n = await Ue(t, e.automation_entity_id);
				this._notice = [W(t, "routines.conversions.converted", {
					alias: e.alias,
					device: n.device_name
				})];
			} catch (e) {
				this._notice = [await G(t, e)];
			}
			await this.refresh();
		}
	}
	_edit(e) {
		this._editing = e.device_id, this._draft = gt(e.settings), this._editError = void 0, this._devices === void 0 && this._loadDevices();
	}
	_setDraft(e, t) {
		this._draft !== void 0 && (this._draft = {
			...this._draft,
			[e]: t
		});
	}
	async _save(e, t) {
		e.preventDefault();
		let n = this.hass;
		if (n === void 0 || this._draft === void 0) return;
		let r = vt(t.settings, this._draft);
		if (Object.keys(r).length === 0) {
			this._editing = void 0;
			return;
		}
		try {
			let e = await Pe(n, t.device_id, r);
			this._routines = (this._routines ?? []).map((t) => t.device_id === e.device_id ? e : t), this._editing = void 0, this._editError = void 0, this._notice = [W(n, "routines.edit.saved", { device: t.device_name })];
		} catch (e) {
			this._editError = {
				text: await G(n, e),
				setting: Ze(e)
			};
		}
	}
	render() {
		let e = this.hass;
		if (this._routines === void 0) return D`<section>
        ${this._error === void 0 ? D`<p class="notice">${W(e, "common.loading")}</p>` : D`<p class="error" role="alert">${this._error}</p>
              <button data-action="retry" @click=${() => void this.refresh()}>${W(e, "common.retry")}</button>`}
      </section>`;
		let t = this._routines.filter((e) => e.status === "detached"), n = this._routines.filter((e) => e.status !== "detached" && Q(e)), r = this._routines.filter((e) => e.status !== "detached" && !Q(e));
		return D`
      <section id="routines">
        <h2>${W(e, "routines.title")}</h2>
        ${this._error === void 0 ? k : D`<p class="error" role="alert">${this._error}</p>`}
        ${this._notice.length === 0 ? k : D`<div class="notice" role="status">${this._notice.map((e) => D`<div>${e}</div>`)}</div>`}
        ${this._renderSelectionBar(r)}
        ${r.length === 0 ? D`<p class="hint">${W(e, "routines.empty")}</p>` : D`<div class="scroll">
              <table>
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        data-select="all"
                        aria-label=${W(e, "routines.select_all")}
                        .checked=${r.every((e) => this._selected.has(e.device_id))}
                        @change=${(e) => this._selectAll(r, e)}
                      />
                    </th>
                    <th>${W(e, "routines.columns.device")}</th>
                    <th>${W(e, "routines.columns.area")}</th>
                    <th>${W(e, "routines.columns.schedule")}</th>
                    <th>${W(e, "routines.columns.status")}</th>
                    <th>${W(e, "routines.columns.next_action")}</th>
                    <th>${W(e, "routines.columns.pause")}</th>
                    <th>${W(e, "routines.columns.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  ${r.map((e) => this._renderRow(e))}
                </tbody>
              </table>
            </div>`}
      </section>
      ${n.length === 0 ? k : this._renderOptedOut(n)}
      ${t.length === 0 ? k : this._renderDetached(t)}
      ${this.renderConversionCandidates()}
      ${this._renderDevices()}
    `;
	}
	renderConversionCandidates() {
		let e = this.hass, t = this._offers ?? [];
		return t.length === 0 ? this._offersError === void 0 ? k : D`<section id="conversions">
            <h2>${W(e, "routines.conversions.title")}</h2>
            <p class="error" role="alert">${this._offersError}</p>
          </section>` : D`<section id="conversions">
      <h2>${W(e, "routines.conversions.title")}</h2>
      <p class="hint">${W(e, "routines.conversions.description")}</p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${W(e, "routines.conversions.automation")}</th>
              <th>${W(e, "routines.columns.device")}</th>
              <th>${W(e, "routines.columns.schedule")}</th>
              <th>${W(e, "routines.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            ${t.map((e) => this._renderOffer(e))}
          </tbody>
        </table>
      </div>
    </section>`;
	}
	_renderOffer(e) {
		let t = this.hass, n = e.automation_entity_id, r = this._confirmConvert === n;
		return D`<tr data-offer=${n}>
        <td>
          <a data-link="automation" href=${H(e.automation_id)} @click=${K}
            >${e.alias}</a
          >
        </td>
        <td>
          <a data-link="device" href=${V(e.device_id)} @click=${K}>${e.device_name}</a>
        </td>
        <td data-cell="sentence">${e.original_sentence}</td>
        <td>
          ${r ? k : D`<button data-action="convert" @click=${() => this._confirmConvert = n}>
                ${W(t, "routines.conversions.convert")}
              </button>`}
        </td>
      </tr>
      ${r ? D`<tr data-confirm-offer=${n}>
            <td colspan="4">
              <p>${W(t, "routines.conversions.confirm", {
			alias: e.alias,
			device: e.device_name
		})}</p>
              <div class="sentences">
                <div data-sentence="original">
                  <strong>${W(t, "routines.conversions.original")}</strong>
                  ${e.original_sentence}
                </div>
                <div data-sentence="routine">
                  <strong>${W(t, "routines.conversions.routine")}</strong>
                  ${e.routine_sentence}
                </div>
              </div>
              <button class="primary" data-action="confirm_convert" @click=${() => void this._convert(e)}>
                ${W(t, "routines.conversions.confirm_convert")}
              </button>
              <button data-action="cancel_convert" @click=${() => this._confirmConvert = void 0}>
                ${W(t, "common.cancel")}
              </button>
            </td>
          </tr>` : k}`;
	}
	_renderOptedOut(e) {
		let t = this.hass;
		return D`<section id="opted-out">
      <h2>${W(t, "routines.opted_out_section.title")}</h2>
      <p class="hint">${W(t, "routines.opted_out_section.description")}</p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${W(t, "routines.columns.device")}</th>
              <th>${W(t, "routines.columns.area")}</th>
              <th>${W(t, "routines.columns.schedule")}</th>
              <th>${W(t, "routines.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            ${e.map((e) => D`<tr data-device=${e.device_id}>
                <td>
                  <a data-link="device" href=${V(e.device_id)} @click=${K}
                    >${e.device_name}</a
                  >
                </td>
                <td>${Y(t, e.area_id)}</td>
                <td data-cell="sentence">${e.sentence ?? W(t, "routines.no_sentence")}</td>
                <td>
                  <button data-action="opt_in_again" @click=${() => void this._optIn([e.device_id])}>
                    ${W(t, "routines.opted_out_section.opt_in_again")}
                  </button>
                  <a data-link="automation" href=${H(e.automation_id)} @click=${K}>
                    ${W(t, "routines.open_automation")}
                  </a>
                </td>
              </tr>`)}
          </tbody>
        </table>
      </div>
    </section>`;
	}
	_selectAll(e, t) {
		let n = t.target.checked;
		this._selected = new Set(n ? e.map((e) => e.device_id) : []);
	}
	_select(e, t) {
		let n = new Set(this._selected);
		t.target.checked ? n.add(e) : n.delete(e), this._selected = n;
	}
	_renderSelectionBar(e) {
		let t = this.hass, n = e.filter((e) => this._selected.has(e.device_id)).length;
		return n === 0 ? k : D`<div class="toolbar" data-selection>
      <span>${W(t, "routines.selection", { count: n })}</span>
      ${[
			"skip_next",
			"pause",
			"resume",
			"enable",
			"disable"
		].map((e) => D`<button data-action=${e} @click=${() => this._actSelection(e)}>
            ${W(t, pt[e])}
          </button>`)}
      ${this._pauseSelection ? this._renderPauseInput([...this._selected]) : k}
    </div>`;
	}
	_renderPauseInput(e) {
		let t = this.hass;
		return D`<span class="field inline" data-pause>
      <label>
        ${W(t, "routines.pause_until")}
        <input
          type="datetime-local"
          name="until"
          .value=${this._pauseUntil}
          @input=${(e) => this._pauseUntil = e.target.value}
        />
      </label>
      <button
        class="primary"
        data-action="confirm_pause"
        ?disabled=${this._pauseUntil === ""}
        @click=${() => this._confirmPause(e)}
      >
        ${W(t, "routines.pause_confirm")}
      </button>
      <button
        data-action="cancel_pause"
        @click=${() => {
			this._pauseRow = void 0, this._pauseSelection = !1;
		}}
      >
        ${W(t, "common.cancel")}
      </button>
    </span>`;
	}
	_renderNextAction(e) {
		let t = this.hass, n = e.next_action;
		return n === null ? W(t, "routines.no_next_action") : W(t, "routines.next_action", {
			verb: dt(t, n.verb),
			time: J(t, n.at, this.timeFormat)
		});
	}
	_renderRow(e) {
		let t = this.hass, n = e.device_id, r = e.paused_until !== null;
		return D`
      <tr data-device=${n}>
        <td>
          <input
            type="checkbox"
            data-select=${n}
            aria-label=${W(t, "routines.select_row", { device: e.device_name })}
            .checked=${this._selected.has(n)}
            @change=${(e) => this._select(n, e)}
          />
        </td>
        <td><a data-link="device" href=${V(n)} @click=${K}>${e.device_name}</a></td>
        <td>${Y(t, e.area_id)}</td>
        <td data-cell="sentence">${e.sentence ?? W(t, "routines.no_sentence")}</td>
        <td data-cell="status">${ut(t, e.status)}</td>
        <td data-cell="next">${this._renderNextAction(e)}</td>
        <td data-cell="pause">
          ${r ? W(t, "routines.paused_until_time", { time: J(t, e.paused_until ?? "", this.timeFormat) }) : W(t, "routines.not_paused")}
        </td>
        <td>
          <button data-action="skip_next" @click=${() => this._actRow("skip_next", n)}>
            ${W(t, "routines.actions.skip_next")}
          </button>
          <button data-action="pause" @click=${() => this._actRow("pause", n)}>
            ${W(t, "routines.actions.pause")}
          </button>
          ${r ? D`<button data-action="resume" @click=${() => this._actRow("resume", n)}>
                ${W(t, "routines.actions.resume")}
              </button>` : k}
          ${e.enabled ? D`<button data-action="disable" @click=${() => this._actRow("disable", n)}>
                ${W(t, "routines.actions.disable")}
              </button>` : D`<button data-action="enable" @click=${() => this._actRow("enable", n)}>
                ${W(t, "routines.actions.enable")}
              </button>`}
          <button data-action="edit" @click=${() => this._edit(e)}>${W(t, "routines.actions.edit")}</button>
          ${this._confirmOptOut === n ? D`<button class="primary" data-action="confirm_opt_out" @click=${() => void this._optOut(n)}>
                  ${W(t, "routines.actions.confirm_opt_out")}
                </button>
                <button data-action="cancel_opt_out" @click=${() => this._confirmOptOut = void 0}>
                  ${W(t, "common.cancel")}
                </button>` : D`<button data-action="opt_out" @click=${() => this._confirmOptOut = n}>
                ${W(t, "routines.actions.opt_out")}
              </button>`}
          <a data-link="automation" href=${H(e.automation_id)} @click=${K}>
            ${W(t, "routines.open_automation")}
          </a>
        </td>
      </tr>
      ${this._pauseRow === n ? D`<tr data-pause-row=${n}>
            <td colspan="8">${this._renderPauseInput(n)}</td>
          </tr>` : k}
      ${this._editing === n && this._draft !== void 0 ? D`<tr class="editor" data-editor=${n}>
            <td colspan="8">${this._renderEditor(e, this._draft)}</td>
          </tr>` : k}
    `;
	}
	_invalid(e) {
		return this._editError?.setting === e ? "true" : "false";
	}
	_label(e) {
		return W(this.hass, ht[e]);
	}
	_renderEditor(e, t) {
		let n = this.hass, r = this._devices?.find((t) => t.device_id === e.device_id)?.targets ?? [], i = r.includes(t.target_entity) ? r : [t.target_entity, ...r], a = (e) => D`<label class="field">
        <span>${this._label(e)}</span>
        <input
          type="number"
          name=${e}
          step="1"
          inputmode="numeric"
          aria-invalid=${this._invalid(e)}
          .value=${String(t[e])}
          @change=${(t) => {
			let n = t.target.value, r = Number(n);
			this._setDraft(e, n !== "" && Number.isInteger(r) ? r : n);
		}}
        />
      </label>`, o = (e) => D`<label class="field">
        <span>${this._label(e)}</span>
        <input
          type="time"
          name=${e}
          aria-invalid=${this._invalid(e)}
          .value=${it(t[e])}
          @change=${(t) => {
			let n = t.target.value;
			this._setDraft(e, n === "" ? null : n);
		}}
        />
      </label>`, s = (e) => D`<label class="field inline">
        <input
          type="checkbox"
          name=${e}
          aria-invalid=${this._invalid(e)}
          .checked=${t[e]}
          @change=${(t) => this._setDraft(e, t.target.checked)}
        />
        <span>${this._label(e)}</span>
      </label>`;
		return D`<form novalidate @submit=${(t) => void this._save(t, e)}>
      <h2 class="wide">${W(n, "routines.edit.title", { device: e.device_name })}</h2>
      <label class="field">
        <span>${this._label("target_entity")}</span>
        <select
          name="target_entity"
          aria-invalid=${this._invalid("target_entity")}
          @change=${(e) => this._setDraft("target_entity", e.target.value)}
        >
          ${i.map((e) => D`<option value=${e} ?selected=${e === t.target_entity}>${e}</option>`)}
        </select>
      </label>
      ${o("on_time")} ${o("off_time")}
      <label class="field">
        <span>${this._label("days")}</span>
        <select
          name="days"
          aria-invalid=${this._invalid("days")}
          @change=${(e) => this._setDraft("days", e.target.value)}
        >
          ${Ae.map((e) => D`<option value=${e} ?selected=${e === t.days}>${W(n, st[e])}</option>`)}
        </select>
      </label>
      ${t.days === "some_days" ? D`<fieldset class="wide" name="day_set" aria-invalid=${this._invalid("day_set")}>
            <legend>${this._label("day_set")}</legend>
            ${R.map((e) => D`<label class="field inline">
                <input
                  type="checkbox"
                  name="day_set"
                  value=${e}
                  .checked=${t.day_set.includes(e)}
                  @change=${(t) => {
			let n = t.target.checked, r = (this._draft?.day_set ?? []).filter((t) => t !== e);
			this._setDraft("day_set", n ? [...r, e] : r);
		}}
                />
                <span>${W(n, ct[e])}</span>
              </label>`)}
          </fieldset>` : k}
      ${t.days === "weekly_schedule" ? D`<label class="field">
            <span>${this._label("schedule_entity")}</span>
            <input
              type="text"
              name="schedule_entity"
              aria-invalid=${this._invalid("schedule_entity")}
              .value=${t.schedule_entity ?? ""}
              @change=${(e) => {
			let t = e.target.value.trim();
			this._setDraft("schedule_entity", t === "" ? null : t);
		}}
            />
          </label>` : k}
      ${a("turn_off_after_min")} ${a("turn_back_on_after_min")} ${a("late_start_window_min")}
      ${s("catch_up")} ${s("respect_manual")} ${s("docked_guard")}
      ${this._editError === void 0 ? k : D`<p class="error wide" role="alert" data-error>${this._editError.text}</p>`}
      <div class="wide">
        <button class="primary" type="submit" data-action="save">${W(n, "common.save")}</button>
        <button type="button" data-action="cancel_edit" @click=${() => this._editing = void 0}>
          ${W(n, "common.cancel")}
        </button>
      </div>
    </form>`;
	}
	_renderDetached(e) {
		let t = this.hass;
		return D`<section id="detached">
      <h2>${W(t, "routines.detached.title")}</h2>
      <p class="hint">${W(t, "routines.detached.description")}</p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${W(t, "routines.columns.device")}</th>
              <th>${W(t, "routines.columns.area")}</th>
              <th>${W(t, "routines.columns.schedule")}</th>
              <th>${W(t, "routines.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            ${e.map((e) => D`<tr data-device=${e.device_id}>
                <td>
                  <a data-link="device" href=${V(e.device_id)} @click=${K}
                    >${e.device_name}</a
                  >
                </td>
                <td>${Y(t, e.area_id)}</td>
                <td data-cell="sentence">${e.sentence ?? W(t, "routines.no_sentence")}</td>
                <td>
                  <a data-link="automation" href=${H(e.automation_id)} @click=${K}>
                    ${W(t, "routines.open_automation")}
                  </a>
                </td>
              </tr>`)}
          </tbody>
        </table>
      </div>
    </section>`;
	}
	_renderDevices() {
		let e = this.hass, t = this._devices, n = new Set((this._routines ?? []).map((e) => e.device_id));
		return D`<section id="devices">
      <h2>${W(e, "routines.devices.title")}</h2>
      <p class="hint">${W(e, "routines.devices.description")}</p>
      ${t === void 0 ? D`<button data-action="load_devices" @click=${() => void this._loadDevices()}>
            ${W(e, "routines.devices.load")}
          </button>` : t.length === 0 ? D`<p class="hint">${W(e, "routines.devices.empty")}</p>` : D`<div class="toolbar">
                <button
                  class="primary"
                  data-action="opt_in_selected"
                  ?disabled=${this._devicesSelected.size === 0}
                  @click=${() => void this._optIn([...this._devicesSelected])}
                >
                  ${W(e, "routines.devices.opt_in_selected")}
                </button>
              </div>
              <div class="scroll">
                <table>
                  <thead>
                    <tr>
                      <th></th>
                      <th>${W(e, "routines.columns.device")}</th>
                      <th>${W(e, "routines.columns.area")}</th>
                      <th>${W(e, "routines.devices.targets")}</th>
                      <th>${W(e, "routines.columns.actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${t.map((t) => D`<tr data-eligible=${t.device_id}>
                        <td>
                          <input
                            type="checkbox"
                            data-select=${t.device_id}
                            aria-label=${W(e, "routines.select_row", { device: t.name })}
                            .checked=${this._devicesSelected.has(t.device_id)}
                            @change=${(e) => {
			let n = new Set(this._devicesSelected);
			e.target.checked ? n.add(t.device_id) : n.delete(t.device_id), this._devicesSelected = n;
		}}
                          />
                        </td>
                        <td>
                          <a data-link="device" href=${V(t.device_id)} @click=${K}
                            >${t.name}</a
                          >
                          ${this._suggested.has(t.device_id) ? D`<span class="badge" data-badge="suggested"
                                >${W(e, "routines.devices.suggested")}</span
                              >` : k}
                          ${n.has(t.device_id) ? D`<span class="badge" data-badge="has_routine"
                                >${W(e, "routines.devices.has_routine")}</span
                              >` : k}
                        </td>
                        <td>${Y(e, t.area_id)}</td>
                        <td>${t.targets.join(", ")}</td>
                        <td>
                          <button data-action="opt_in" @click=${() => void this._optIn([t.device_id])}>
                            ${W(e, "routines.devices.opt_in")}
                          </button>
                        </td>
                      </tr>`)}
                  </tbody>
                </table>
              </div>`}
    </section>`;
	}
};
customElements.get("dr-routines-view") || customElements.define("dr-routines-view", xt);
//#endregion
//#region src/views/settings-view.ts
var St = {
	schedule_scope: {
		kind: "choice",
		choices: {
			all: "settings.choices.schedule_scope.all",
			routines: "settings.choices.schedule_scope.routines",
			none: "settings.choices.schedule_scope.none"
		}
	},
	time_format: {
		kind: "choice",
		choices: {
			auto: "settings.choices.time_format.auto",
			"12h": "settings.choices.time_format.12h",
			"24h": "settings.choices.time_format.24h"
		}
	},
	default_catch_up: { kind: "boolean" },
	default_respect_manual: { kind: "boolean" },
	default_late_start_window_min: { kind: "number" },
	cleanup_after_days: { kind: "number" },
	assign_area: { kind: "boolean" },
	on_removal: {
		kind: "choice",
		choices: {
			keep: "settings.choices.on_removal.keep",
			delete: "settings.choices.on_removal.delete"
		}
	},
	ai_task_entity: { kind: "entity" },
	ai_calls_per_hour: { kind: "number" },
	offer_conversions: { kind: "boolean" },
	raise_conflict_repairs: { kind: "boolean" }
}, Ct = {
	schedule_scope: {
		name: "settings.fields.schedule_scope.name",
		description: "settings.fields.schedule_scope.description"
	},
	time_format: {
		name: "settings.fields.time_format.name",
		description: "settings.fields.time_format.description"
	},
	default_catch_up: {
		name: "settings.fields.default_catch_up.name",
		description: "settings.fields.default_catch_up.description"
	},
	default_respect_manual: {
		name: "settings.fields.default_respect_manual.name",
		description: "settings.fields.default_respect_manual.description"
	},
	default_late_start_window_min: {
		name: "settings.fields.default_late_start_window_min.name",
		description: "settings.fields.default_late_start_window_min.description"
	},
	cleanup_after_days: {
		name: "settings.fields.cleanup_after_days.name",
		description: "settings.fields.cleanup_after_days.description"
	},
	assign_area: {
		name: "settings.fields.assign_area.name",
		description: "settings.fields.assign_area.description"
	},
	on_removal: {
		name: "settings.fields.on_removal.name",
		description: "settings.fields.on_removal.description"
	},
	ai_task_entity: {
		name: "settings.fields.ai_task_entity.name",
		description: "settings.fields.ai_task_entity.description"
	},
	ai_calls_per_hour: {
		name: "settings.fields.ai_calls_per_hour.name",
		description: "settings.fields.ai_calls_per_hour.description"
	},
	offer_conversions: {
		name: "settings.fields.offer_conversions.name",
		description: "settings.fields.offer_conversions.description"
	},
	raise_conflict_repairs: {
		name: "settings.fields.raise_conflict_repairs.name",
		description: "settings.fields.raise_conflict_repairs.description"
	}
}, wt = {
	rebuild_index: {
		name: "settings.maintenance.actions.rebuild_index.name",
		description: "settings.maintenance.actions.rebuild_index.description"
	},
	reinstall_blueprint: {
		name: "settings.maintenance.actions.reinstall_blueprint.name",
		description: "settings.maintenance.actions.reinstall_blueprint.description"
	},
	clean_up_now: {
		name: "settings.maintenance.actions.clean_up_now.name",
		description: "settings.maintenance.actions.clean_up_now.description"
	},
	refresh_summaries: {
		name: "settings.maintenance.actions.refresh_summaries.name",
		description: "settings.maintenance.actions.refresh_summaries.description"
	}
}, Tt = [
	["version", "health.attributes.version"],
	["commit", "health.attributes.commit"],
	["branch", "health.attributes.branch"],
	["deployed_at", "health.attributes.deployed_at"],
	["channel", "health.attributes.channel"],
	["blueprint_schema", "health.attributes.blueprint_schema"],
	["blueprint_status", "health.attributes.blueprint_status"],
	["owned_count", "health.attributes.owned_count"],
	["loaded_count", "health.attributes.loaded_count"],
	["issues", "health.attributes.issues"],
	["ha_version", "health.attributes.ha_version"],
	["last_reconcile", "health.attributes.last_reconcile"]
], Et = {
	ok: "health.state.ok",
	degraded: "health.state.degraded",
	error: "health.state.error"
};
function Dt(e, t) {
	let n = St[e];
	return n === void 0 ? typeof t == "boolean" ? { kind: "boolean" } : typeof t == "number" ? { kind: "number" } : { kind: "entity" } : n;
}
function Ot(e, t) {
	let n = {};
	for (let [r, i] of Object.entries(t)) JSON.stringify(e[r]) !== JSON.stringify(i) && (n[r] = i);
	return n;
}
var kt = class extends I {
	static properties = {
		hass: { attribute: !1 },
		narrow: { type: Boolean },
		timeFormat: { attribute: !1 },
		_settings: { state: !0 },
		_draft: { state: !0 },
		_error: { state: !0 },
		_saveError: { state: !0 },
		_saved: { state: !0 },
		_maintenance: { state: !0 },
		_maintenanceError: { state: !0 }
	};
	static styles = [q, o`
      form {
        display: grid;
        gap: 0 var(--ha-space-4, 16px);
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      }

      .wide {
        grid-column: 1 / -1;
      }

      dl {
        display: grid;
        gap: var(--ha-space-1, 4px) var(--ha-space-4, 16px);
        grid-template-columns: max-content 1fr;
        margin: 0;
      }

      dt {
        color: var(--secondary-text-color, #727272);
      }

      dd {
        margin: 0;
        overflow-wrap: anywhere;
      }

      .maintenance {
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        padding: var(--ha-space-2, 8px) 0;
      }

      .state-ok {
        color: var(--success-color, #43a047);
      }

      .state-degraded {
        color: var(--warning-color, #ffa600);
      }

      .state-error {
        color: var(--error-color, #db4437);
      }
    `];
	_started = !1;
	constructor() {
		super(), this.narrow = !1, this._draft = {}, this._saved = !1, this._maintenance = {};
	}
	willUpdate(e) {
		e.has("hass") && this.hass !== void 0 && !this._started && (this._started = !0, this.refreshSettings());
	}
	async refreshSettings() {
		let e = this.hass;
		if (e !== void 0) try {
			let t = { ...await ze(e) };
			this._settings = t, this._draft = { ...t }, this._error = void 0;
		} catch (t) {
			this._error = await G(e, t);
		}
	}
	refreshHealth() {
		this.requestUpdate();
	}
	_set(e, t) {
		this._draft = {
			...this._draft,
			[e]: t
		}, this._saved = !1;
	}
	async _save(e) {
		e.preventDefault();
		let t = this.hass;
		if (t === void 0 || this._settings === void 0) return;
		let n = Ot(this._settings, this._draft);
		if (Object.keys(n).length !== 0) try {
			let e = { ...await Be(t, n) };
			this._settings = e, this._draft = { ...e }, this._saveError = void 0, this._saved = !0;
		} catch (e) {
			this._saveError = {
				text: await G(t, e),
				setting: Ze(e)
			}, this._saved = !1;
		}
	}
	async _maintain(e, t) {
		let n = this.hass;
		if (n !== void 0) {
			this._maintenanceError = void 0;
			try {
				let r = await Ve(n, e, t);
				this._maintenance = {
					...this._maintenance,
					[e]: {
						phase: t ? "preview" : "done",
						report: r
					}
				};
			} catch (t) {
				this._maintenanceError = {
					action: e,
					text: await G(n, t)
				};
			}
		}
	}
	_dismiss(e) {
		let t = { ...this._maintenance };
		delete t[e], this._maintenance = t;
	}
	render() {
		return D`${this._renderSettings()} ${this._renderMaintenance()} ${this._renderHealth()}`;
	}
	_renderSettings() {
		let e = this.hass, t = this._settings, n = t === void 0 ? 0 : Object.keys(Ot(t, this._draft)).length;
		return D`<section id="settings">
      <h2>${W(e, "settings.title")}</h2>
      <p class="hint">${W(e, "settings.description")}</p>
      ${this._error === void 0 ? k : D`<p class="error" role="alert">${this._error}</p>`}
      ${t === void 0 ? this._error === void 0 ? D`<p class="notice">${W(e, "common.loading")}</p>` : D`<button data-action="retry" @click=${() => void this.refreshSettings()}>
              ${W(e, "common.retry")}
            </button>` : D`<form novalidate @submit=${(e) => void this._save(e)}>
            ${Object.keys(t).map((e) => this._renderField(e))}
            ${this._saveError === void 0 ? k : D`<p class="error wide" role="alert" data-error>${this._saveError.text}</p>`}
            ${this._saved ? D`<p class="notice wide" role="status">${W(e, "settings.saved")}</p>` : k}
            <div class="wide">
              <button class="primary" type="submit" data-action="save" ?disabled=${n === 0}>
                ${W(e, "common.save")}
              </button>
            </div>
          </form>`}
    </section>`;
	}
	_renderField(e) {
		let t = this.hass, n = this._draft[e], r = Dt(e, n), i = Ct[e], a = i === void 0 ? e : W(t, i.name), o = i === void 0 ? k : D`<span class="description">${W(t, i.description)}</span>`, s = this._saveError?.setting === e ? "true" : "false";
		if (r.kind === "boolean") return D`<label class="field" data-setting=${e}>
        <span class="field inline">
          <input
            type="checkbox"
            name=${e}
            aria-invalid=${s}
            .checked=${n === !0}
            @change=${(t) => this._set(e, t.target.checked)}
          />
          <span>${a}</span>
        </span>
        ${o}
      </label>`;
		let c;
		return c = r.kind === "choice" ? D`<select
        name=${e}
        aria-invalid=${s}
        @change=${(t) => this._set(e, t.target.value)}
      >
        ${Object.entries(r.choices).map(([e, r]) => D`<option value=${e} ?selected=${e === n}>${W(t, r)}</option>`)}
      </select>` : r.kind === "number" ? D`<input
        type="number"
        name=${e}
        step="1"
        inputmode="numeric"
        aria-invalid=${s}
        .value=${n == null ? "" : String(n)}
        @change=${(t) => {
			let n = t.target.value, r = Number(n);
			this._set(e, n !== "" && Number.isFinite(r) ? r : n);
		}}
      />` : D`<input
        type="text"
        name=${e}
        aria-invalid=${s}
        placeholder=${W(t, "common.none")}
        .value=${typeof n == "string" ? n : ""}
        @change=${(t) => {
			let n = t.target.value.trim();
			this._set(e, n === "" ? null : n);
		}}
      />`, D`<label class="field" data-setting=${e}>
      <span>${a}</span>
      ${c} ${o}
    </label>`;
	}
	_renderMaintenance() {
		let e = this.hass;
		return D`<section id="maintenance">
      <h2>${W(e, "settings.maintenance.title")}</h2>
      <p class="hint">${W(e, "settings.maintenance.description")}</p>
      ${je.map((e) => this._renderAction(e))}
    </section>`;
	}
	_renderAction(e) {
		let t = this.hass, n = this._maintenance[e], r = this._maintenanceError?.action === e ? this._maintenanceError.text : void 0, i = k;
		if (n?.phase === "preview") {
			let r = n.report.would_change;
			i = D`<div data-report="preview">
        <p>
          ${r.length === 0 ? W(t, "settings.maintenance.would_change_none") : W(t, "settings.maintenance.would_change", { count: r.length })}
        </p>
        ${r.length === 0 ? k : D`<ul>${r.map((e) => D`<li>${e}</li>`)}</ul>`}
        <button class="primary" data-action="run" @click=${() => void this._maintain(e, !1)}>
          ${W(t, "settings.maintenance.run_now")}
        </button>
        <button data-action="cancel" @click=${() => this._dismiss(e)}>${W(t, "common.cancel")}</button>
      </div>`;
		} else if (n?.phase === "done") {
			let r = n.report.changed;
			i = D`<div data-report="done">
        <p role="status">
          ${r.length === 0 ? W(t, "settings.maintenance.changed_none") : W(t, "settings.maintenance.changed", { count: r.length })}
        </p>
        ${r.length === 0 ? k : D`<ul>${r.map((e) => D`<li>${e}</li>`)}</ul>`}
        <button data-action="dismiss" @click=${() => this._dismiss(e)}>${W(t, "common.close")}</button>
      </div>`;
		}
		return D`<div class="maintenance" data-maintenance=${e}>
      <strong>${W(t, wt[e].name)}</strong>
      <p class="hint">${W(t, wt[e].description)}</p>
      ${n === void 0 ? D`<button data-action="preview" @click=${() => void this._maintain(e, !0)}>
            ${W(t, "settings.maintenance.preview")}
          </button>` : i}
      ${r === void 0 ? k : D`<p class="error" role="alert">${r}</p>`}
    </div>`;
	}
	_renderHealth() {
		let e = this.hass, t = e?.states[ke];
		if (t === void 0) return D`<section id="health">
        <h2>${W(e, "health.title")}</h2>
        <p class="hint" data-health="missing">${W(e, "health.missing")}</p>
      </section>`;
		let n = Et[t.state];
		return D`<section id="health">
      <h2>${W(e, "health.title")}</h2>
      <p data-health="state" class=${`state-${t.state}`}>
        ${n === void 0 ? t.state : W(e, n)}
      </p>
      <dl>
        ${Tt.filter(([e]) => e in t.attributes).map(([n, r]) => D`<dt>${W(e, r)}</dt>
              <dd data-attribute=${n}>${this._healthValue(t.attributes[n])}</dd>`)}
      </dl>
    </section>`;
	}
	_healthValue(e) {
		return e == null || Array.isArray(e) && e.length === 0 ? W(this.hass, "common.none") : Array.isArray(e) ? e.map(String).join(", ") : typeof e == "string" && /^\d{4}-\d{2}-\d{2}T/.test(e) ? J(this.hass, e, this.timeFormat) : String(e);
	}
};
customElements.get("dr-settings-view") || customElements.define("dr-settings-view", kt);
//#endregion
//#region src/views/today-view.ts
function At(e, t) {
	let n = /* @__PURE__ */ new Map();
	for (let e of t) {
		let t = n.get(e.area_id) ?? [];
		t.push(e), n.set(e.area_id, t);
	}
	return [...n.entries()].map(([t, n]) => ({
		areaId: t,
		name: Y(e, t),
		items: [...n].sort((e, t) => Date.parse(e.time) - Date.parse(t.time))
	})).sort((e, t) => e.areaId === null || t.areaId === null ? e.areaId === t.areaId ? 0 : e.areaId === null ? 1 : -1 : e.name.localeCompare(t.name) || e.areaId.localeCompare(t.areaId));
}
var jt = class extends I {
	static properties = {
		hass: { attribute: !1 },
		narrow: { type: Boolean },
		timeFormat: { attribute: !1 },
		_schedule: { state: !0 },
		_date: { state: !0 },
		_error: { state: !0 }
	};
	static styles = [q, o`
      .toolbar {
        align-items: center;
        display: flex;
        gap: var(--ha-space-2, 8px);
        margin: 0 0 var(--ha-space-3, 12px);
      }

      h3 {
        font-size: var(--ha-font-size-m, 14px);
        font-weight: var(--ha-font-weight-medium, 500);
        margin: var(--ha-space-4, 16px) 0 var(--ha-space-2, 8px);
      }

      tr.conflict td:first-child {
        border-inline-start: 4px solid var(--warning-color, #ffa600);
      }

      .badge.conflict {
        color: var(--warning-color, #ffa600);
      }

      td.time {
        white-space: nowrap;
      }
    `];
	_started = !1;
	constructor() {
		super(), this.narrow = !1;
	}
	willUpdate(e) {
		e.has("hass") && this.hass !== void 0 && !this._started && (this._started = !0, this.refresh());
	}
	async refresh() {
		let e = this.hass;
		if (e !== void 0) try {
			this._schedule = await Re(e, this._date), this._date = this._schedule.date, this._error = void 0;
		} catch (t) {
			this._error = await G(e, t);
		}
	}
	_pick(e) {
		let t = e.target.value;
		this._date = t === "" ? void 0 : t, this.refresh();
	}
	render() {
		let e = this.hass, t = this._schedule;
		return D`<section>
      <h2>${W(e, "today.title")}</h2>
      <div class="toolbar">
        <label class="field inline">
          <span>${W(e, "today.date")}</span>
          <input type="date" name="date" .value=${this._date ?? ""} @change=${(e) => this._pick(e)} />
        </label>
      </div>
      ${this._error === void 0 ? k : D`<p class="error" role="alert">${this._error}</p>`}
      ${t === void 0 ? this._error === void 0 ? D`<p class="notice">${W(e, "common.loading")}</p>` : k : t.items.length === 0 ? D`<p class="hint">${W(e, "today.empty")}</p>` : At(e, t.items).map((e) => this._renderGroup(e))}
    </section>`;
	}
	_renderGroup(e) {
		let t = this.hass;
		return D`<div data-area=${e.areaId ?? ""}>
      <h3>${e.name}</h3>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${W(t, "today.columns.time")}</th>
              <th>${W(t, "today.columns.device")}</th>
              <th>${W(t, "today.columns.action")}</th>
              <th>${W(t, "today.columns.source")}</th>
            </tr>
          </thead>
          <tbody>
            ${e.items.map((e) => this._renderItem(e))}
          </tbody>
        </table>
      </div>
    </div>`;
	}
	_renderConditions(e) {
		let t = this.hass;
		return e <= 0 ? k : D`<span class="badge" data-conditions=${e}>
      ${e === 1 ? W(t, "today.condition_one") : W(t, "today.condition_many", { count: e })}
    </span>`;
	}
	_renderItem(e) {
		let t = this.hass;
		return D`<tr class=${e.conflict ? "conflict" : ""} data-item ?data-conflict=${e.conflict}>
      <td class="time">${rt(t, e.time, this.timeFormat)}</td>
      <td>
        <a data-link="device" href=${V(e.device_id)} @click=${K}
          >${e.device_name ?? X(t, e.device_id)}</a
        >
      </td>
      <td>
        ${dt(t, e.action)}
        ${e.conflict ? D`<span class="badge conflict">${W(t, "today.conflict")}</span>` : k}
        ${this._renderConditions(e.conditions ?? 0)}
      </td>
      <td>
        ${ft(t, e.kind)}
        ${e.kind === "routine" ? k : D`<span class="muted" title=${e.automation}>${e.alias ?? e.automation}</span>`}
      </td>
    </tr>`;
	}
};
customElements.get("dr-today-view") || customElements.define("dr-today-view", jt);
//#endregion
//#region src/device-routines-panel.ts
var $ = [
	"routines",
	"today",
	"settings"
], Mt = {
	routines: "panel.tabs.routines",
	today: "panel.tabs.today",
	settings: "panel.tabs.settings"
}, Nt = "M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z";
function Pt(e) {
	let t = e?.path.split("/").find((e) => e !== "");
	return $.find((e) => e === t);
}
var Ft = class extends I {
	static properties = {
		hass: { attribute: !1 },
		narrow: {
			type: Boolean,
			reflect: !0
		},
		route: { attribute: !1 },
		panel: { attribute: !1 },
		_view: { state: !0 },
		_timeFormat: { state: !0 }
	};
	static styles = [q, o`
      :host {
        background: var(--primary-background-color, #fafafa);
        min-height: 100vh;
      }

      header {
        align-items: center;
        background: var(--app-header-background-color, var(--primary-color, #03a9f4));
        color: var(--app-header-text-color, var(--text-primary-color, #fff));
        display: flex;
        gap: var(--ha-space-2, 8px);
        min-height: var(--header-height, 56px);
        padding: 0 var(--ha-space-4, 16px);
      }

      header h1 {
        font-size: var(--ha-font-size-xl, 20px);
        font-weight: var(--ha-font-weight-normal, 400);
        margin: 0;
      }

      header button.menu {
        border: none;
        color: inherit;
        margin: 0;
        padding: var(--ha-space-2, 8px);
      }

      header button.menu svg {
        display: block;
        fill: currentColor;
        height: 24px;
        width: 24px;
      }

      nav {
        background: var(--card-background-color, #fff);
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        display: flex;
        gap: var(--ha-space-1, 4px);
        padding: 0 var(--ha-space-4, 16px);
      }

      nav button {
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        color: var(--secondary-text-color, #727272);
        margin: 0;
        padding: var(--ha-space-3, 12px) var(--ha-space-4, 16px);
      }

      nav button[aria-selected="true"] {
        border-bottom-color: var(--primary-color, #03a9f4);
        color: var(--primary-color, #03a9f4);
      }

      main {
        margin: 0 auto;
        max-width: 1200px;
        padding: var(--ha-space-4, 16px);
      }

      :host([narrow]) main {
        padding: var(--ha-space-2, 8px);
      }
    `];
	_unsubscribe;
	_timeFormatRead = !1;
	constructor() {
		super(), this.narrow = !1, this._view = "routines";
	}
	connectedCallback() {
		super.connectedCallback(), this._subscribe();
	}
	disconnectedCallback() {
		super.disconnectedCallback();
		let e = this._unsubscribe;
		this._unsubscribe = void 0, e?.then((e) => e?.());
	}
	willUpdate(e) {
		e.has("route") && (this._view = Pt(this.route) ?? this._view), e.has("hass") && (this._subscribe(), this.hass !== void 0 && !this._timeFormatRead && (this._timeFormatRead = !0, this._readTimeFormat()));
	}
	async _readTimeFormat() {
		let e = this.hass;
		if (e !== void 0) try {
			this._timeFormat = (await ze(e)).time_format;
		} catch {
			this._timeFormat = void 0;
		}
	}
	_subscribe() {
		let e = this.hass;
		e !== void 0 && this.isConnected && this._unsubscribe === void 0 && (this._unsubscribe = We(e, (e) => this._heard(e)).catch(() => void 0));
	}
	_heard(e) {
		let t = this.renderRoot;
		switch (e.kind) {
			case "routine_changed":
				e.device_id !== null && t.querySelector("dr-routines-view")?.refreshRoutine(e.device_id);
				break;
			case "schedule_changed":
				t.querySelector("dr-today-view")?.refresh(), t.querySelector("dr-routines-view")?.refreshConversions();
				break;
			case "settings_changed":
				this._readTimeFormat(), t.querySelector("dr-settings-view")?.refreshSettings();
				break;
			case "health_changed": t.querySelector("dr-settings-view")?.refreshHealth();
		}
	}
	_show(e) {
		e !== this._view && (this._view = e, this.route !== void 0 && Qe(`${this.route.prefix}/${e}`));
	}
	render() {
		let e = this.hass;
		return D`
      <header>
        ${this.narrow ? D`<button
              class="menu"
              aria-label=${W(e, "panel.menu")}
              @click=${() => this.dispatchEvent(new Event("hass-toggle-menu", {
			bubbles: !0,
			composed: !0
		}))}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${Nt}></path></svg>
            </button>` : k}
        <h1>${W(e, "panel.title")}</h1>
      </header>
      <nav role="tablist">
        ${$.map((t) => D`<button
              role="tab"
              data-view=${t}
              aria-selected=${t === this._view ? "true" : "false"}
              @click=${() => this._show(t)}
            >
              ${W(e, Mt[t])}
            </button>`)}
      </nav>
      <main role="tabpanel">${this._renderView()}</main>
    `;
	}
	_renderView() {
		switch (this._view) {
			case "today": return D`<dr-today-view
          .hass=${this.hass}
          .timeFormat=${this._timeFormat}
          ?narrow=${this.narrow}
        ></dr-today-view>`;
			case "settings": return D`<dr-settings-view
          .hass=${this.hass}
          .timeFormat=${this._timeFormat}
          ?narrow=${this.narrow}
        ></dr-settings-view>`;
			default: return D`<dr-routines-view
          .hass=${this.hass}
          .timeFormat=${this._timeFormat}
          ?narrow=${this.narrow}
        ></dr-routines-view>`;
		}
	}
};
customElements.get("device-routines-panel") || customElements.define("device-routines-panel", Ft);
//#endregion
export { Ft as DeviceRoutinesPanel, $ as VIEWS };
