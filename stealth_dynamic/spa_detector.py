"""SPADetector — Erkennt Single-Page-App Frameworks + Framework-spezifische Element-Suche."""
import json, logging
logger = logging.getLogger(__name__)

# CDP-JS Script zur Framework-Erkennung
DETECT_SCRIPT = """
(() => {
    const d = {
        react: typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ !== 'undefined',
        react_root: !!document.getElementById('root'),
        angular: typeof window.angular !== 'undefined',
        angular_attr: !!document.querySelector('[ng-version]'),
        vue: typeof __VUE_DEVTOOLS_GLOBAL_HOOK__ !== 'undefined',
        vue_app: !!document.querySelector('#app'),
        jquery: typeof window.jQuery !== 'undefined',
        nextjs: !!document.querySelector('__NEXT_DATA__') || !!(document.getElementById('__next')),
        nuxt: !!document.getElementById('__nuxt'),
        gatsby: !!(document.getElementById('___gatsby')),
        data_testid: document.querySelectorAll('[data-testid],[data-cy],[data-test]').length,
        app_root: document.querySelectorAll('#root,#app,#__next,#__nuxt,main,[role=main]').length,
        mt: typeof MutationObserver !== 'undefined',
        body_children: document.body?.children?.length || 0,
        has_inputs: document.querySelectorAll('input,select,textarea,button').length,
        spa_indicators: 0,
        framework: 'unknown'
    };
    if (d.react || d.react_root || d.nextjs || d.gatsby) d.framework = 'React';
    else if (d.angular || d.angular_attr) d.framework = 'Angular';
    else if (d.vue || d.vue_app || d.nuxt) d.framework = 'Vue';
    else if (d.jquery) d.framework = 'jQuery';
    d.spa_indicators = (d.react?1:0)+(d.react_root?1:0)+(d.angular?1:0)+(d.angular_attr?1:0)
        +(d.vue?1:0)+(d.vue_app?1:0)+(d.jquery?1:0)+(d.nextjs?1:0)+(d.nuxt?1:0)+(d.gatsby?1:0);
    return d;
})()
"""

# Framework-spezifische Selektoren für Form-Elemente
FRAMEWORK_SELECTORS = {
    "React": [
        'input[type="radio"]', 'input[type="checkbox"]', 'input[type="text"]',
        'input[type="number"]', 'select', 'textarea', 'button',
        '[role="radio"]', '[role="checkbox"]', '[role="button"]',
        '[data-testid]', '[data-cy]', '[data-test]',
    ],
    "Angular": [
        'input[type="radio"]', 'input[type="checkbox"]', 'input[type="text"]',
        'input[type="number"]', 'select', 'textarea', 'button',
        '[ng-model]', '[formcontrolname]', '[formControlName]',
    ],
    "Vue": [
        'input[type="radio"]', 'input[type="checkbox"]', 'input[type="text"]',
        'input[type="number"]', 'select', 'textarea', 'button',
        '[v-model]', '[data-v-]',
    ],
    "jQuery": [
        'input[type="radio"]', 'input[type="checkbox"]', 'input[type="text"]',
        'input[type="number"]', 'select', 'textarea', 'button',
        '.radio', '.checkbox', '.btn', '.input',
    ],
    "unknown": [
        'input[type="radio"]', 'input[type="checkbox"]', 'input[type="text"]',
        'input[type="number"]', 'select', 'textarea', 'button',
        '[role="radio"]', '[role="checkbox"]', '[role="button"]',
        'label', 'a[href]',
    ],
}

def detect_framework(ws) -> dict:
    """Sendet CDP-JS Detect-Script und gibt Framework-Dict zurück."""
    import websocket
    try:
        ws.send(json.dumps({"id":999,"method":"Runtime.evaluate","params":{"expression":DETECT_SCRIPT}}))
        resp = json.loads(ws.recv())
        result = resp.get("result",{}).get("result",{}).get("value",{})
        logger.info("SPA: %s (indicators=%d, inputs=%d, testid=%d)",
                     result.get("framework","?"), result.get("spa_indicators",0),
                     result.get("has_inputs",0), result.get("data_testid",0))
        return result
    except Exception as e:
        logger.warning("Framework detection failed: %s", e)
        return {"framework": "unknown", "error": str(e)}

def find_elements_script(framework: str) -> str:
    """Erzeugt CDP-JS Script zum Finden aller Form-Elemente (Framework-spezifisch)."""
    selectors = FRAMEWORK_SELECTORS.get(framework, FRAMEWORK_SELECTORS["unknown"])
    sel_str = ", ".join(f'"{s}"' for s in selectors)
    return f"""
    (() => {{
        const els = document.querySelectorAll('{sel_str}');
        const results = [];
        const seen = new Set();
        els.forEach(el => {{
            const key = (el.id||'') + ':' + (el.name||'') + ':' + el.type;
            if (seen.has(key)) return;
            seen.add(key);
            const rect = el.getBoundingClientRect();
            const labels = el.labels ? Array.from(el.labels).map(l=>l.textContent.trim().substring(0,40)).filter(Boolean) : [];
            const parentText = (el.parentElement?.textContent || '').trim().substring(0,40);
            results.push({{
                tag: el.tagName, type: el.type || '?',
                id: (el.id||'').substring(0,20), name: (el.getAttribute('name')||'').substring(0,20),
                value: (el.value||'').substring(0,20), checked: !!el.checked,
                visible: rect.width>0 && rect.height>0,
                x: Math.round(rect.x), y: Math.round(rect.y),
                w: Math.round(rect.width), h: Math.round(rect.height),
                role: el.getAttribute('role') || '',
                testid: el.getAttribute('data-testid') || el.getAttribute('data-cy') || '',
                labels: labels,
                parentText: parentText,
            }});
        }});
        return results.slice(0,60);
    }})()
    """

def wait_stable_dom_script(timeout_ms=2000) -> str:
    """CDP-JS Script: wartet mit MutationObserver bis DOM stabil ist."""
    return f"""
    (() => {{
        const MAX_WAIT = {timeout_ms};
        return new Promise((resolve) => {{
            const start = Date.now();
            let timeout = setTimeout(() => {{
                observer.disconnect();
                resolve({{stable: true, reason: 'timeout', ms: Date.now()-start}});
            }}, MAX_WAIT);
            let mutations = 0;
            const observer = new MutationObserver(() => {{
                mutations++;
                clearTimeout(timeout);
                timeout = setTimeout(() => {{
                    observer.disconnect();
                    resolve({{stable: true, reason: 'no_mutations', ms: Date.now()-start, mutations}});
                }}, 200);
            }});
            observer.observe(document.body || document.documentElement, {{childList:true,subtree:true,attributes:false}});
            // Also check if DOM is already loaded
            if (document.readyState === 'complete' && document.body) {{
                // Fire after microtasks
                setTimeout(() => {{
                    if (mutations === 0) {{
                        clearTimeout(timeout);
                        observer.disconnect();
                        resolve({{stable: true, reason: 'already_loaded', ms: Date.now()-start}});
                    }}
                }}, 50);
            }}
        }});
    }})()
    """
