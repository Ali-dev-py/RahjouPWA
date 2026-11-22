const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('static/js/filter-state.js', 'utf8');
function browser({url='https://app.test/customers/', saved={}, marked=true, state=null, scope='user1', blocked=false}={}) {
    const map = new Map(Object.entries(saved));
    const events = {}, windowEvents = {}, redirects=[];
    let address = new URL(url);
    const location = {get pathname(){return address.pathname;}, get search(){return address.search;},
        get hash(){return address.hash;}, get href(){return address.href;}, get origin(){return address.origin;},
        replace(value){redirects.push(value);}};
    const history = {state, replaceState(value, unused, url){this.state=value; address=new URL(url,address);}};
    const storage = {get length(){return map.size;}, key(i){return [...map.keys()][i];},
        getItem(k){if(blocked)throw Error('blocked');return map.get(k)||null;},
        setItem(k,v){map.set(k,v);}, removeItem(k){map.delete(k);}};
    const context = {URL,URLSearchParams,location,history,sessionStorage:storage,
        FormData: class { constructor(form){return form.entries;} },
        document:{currentScript:{dataset:{filterScope:scope,filterPage:marked?'1':''}}, addEventListener(n,fn){events[n]=fn;}},
        window:{addEventListener(n,fn){windowEvents[n]=fn;}}};
    vm.runInNewContext(code,context);
    return {events,windowEvents,redirects,history,location,map,stored:()=>JSON.parse(map.get('rahjou.filters.'+scope)||'{}')};
}
const saved=(rows)=>({'rahjou.filters.user1':JSON.stringify(rows)});
test('bare return restores saved filters and pagination',()=>{
    const b=browser({saved:saved({'/customers/':{query:'?province=P1&q=test&page=3'}})});
    assert.deepEqual(b.redirects,['/customers/?province=P1&q=test&page=3']);
});
test('explicit query always wins, including deliberate reset values',()=>{
    const b=browser({url:'https://app.test/customers/?status=all',saved:saved({'/customers/':{query:'?status=debtor'}})});
    assert.equal(b.redirects.length,0);
    assert.equal(b.stored()['/customers/'].query,'?status=all');
});
test('client-side changes and clearing are remembered immediately',()=>{
    const b=browser();
    b.history.replaceState({},'','/customers/?q=ali&city=C');
    assert.equal(b.stored()['/customers/'].query,'?q=ali&city=C');
    b.history.replaceState({},'','/customers/');
    assert.equal(b.stored()['/customers/'].query,'');
});
test('real browser-history default entry does not restore newer filters',()=>{
    const b=browser({state:{rahjouFilterPath:'/customers/'},saved:saved({'/customers/':{query:'?city=C'}})});
    assert.equal(b.redirects.length,0);
    assert.equal(b.stored()['/customers/'].query,'');
});
test('detail-page back link carries saved query; external and explicit links are untouched',()=>{
    const b=browser({marked:false,url:'https://app.test/customers/C1/',saved:saved({'/customers/':{query:'?city=C&page=2'}})});
    const click=(href)=>{const link={href,hasAttribute:()=>false};b.events.click({target:{closest:()=>link}});return link.href;};
    assert.equal(click('https://app.test/customers/'),'https://app.test/customers/?city=C&page=2');
    assert.equal(click('https://app.test/customers/?status=all'),'https://app.test/customers/?status=all');
    assert.equal(click('https://other.test/customers/'),'https://other.test/customers/');
});
test('explicit filter reset deletes saved state',()=>{
    const b=browser({url:'https://app.test/customers/?filters_reset=1',saved:saved({'/customers/':{query:'?q=test'}})});
    assert.deepEqual(b.redirects,['/customers/']);
    assert.equal(b.stored()['/customers/'],undefined);
});
test('new login cannot reuse previous session state',()=>{
    const b=browser({scope:'user2',saved:saved({'/customers/':{query:'?q=private'}})});
    assert.equal(b.map.has('rahjou.filters.user1'),false);
    assert.equal(b.redirects.length,0);
});
test('blocked or malformed storage never breaks navigation',()=>{
    assert.doesNotThrow(()=>browser({blocked:true}));
    assert.doesNotThrow(()=>browser({saved:{'rahjou.filters.user1':'invalid json'}}));
});
test('separate detail paths keep independent filter state',()=>{
    const b=browser({url:'https://app.test/customers/C1/?type=pay',saved:saved({'/customers/C2/':{query:'?type=factor'}})});
    assert.equal(b.stored()['/customers/C1/'].query,'?type=pay');
    assert.equal(b.stored()['/customers/C2/'].query,'?type=factor');
});
test('GET form submissions save defaults and ignore POST forms',()=>{
    const b=browser({url:'https://app.test/income-report/?period=custom'});
    b.events.submit({target:{method:'get',action:b.location.href,entries:[['period','month']]}});
    assert.equal(b.stored()['/income-report/'].query,'?period=month');
    b.events.submit({target:{method:'post',action:b.location.href,entries:[['password','secret']]}});
    assert.equal(b.stored()['/income-report/'].query,'?period=month');
});
test('bfcache remembers current page without overwriting other page state',()=>{
    const b=browser({url:'https://app.test/customers/?city=C'});
    b.map.set('rahjou.filters.user1',JSON.stringify({'/customers/':{query:'?city=C'},'/factors/':{query:'?q=100'}}));
    b.windowEvents.pageshow();
    assert.equal(b.stored()['/factors/'].query,'?q=100');
});
test('reset link clears remembered state rather than restoring it',()=>{
    const b=browser({marked:false,url:'https://app.test/customers/C1/',saved:saved({'/customers/':{query:'?q=old'}})});
    const link={href:'https://app.test/customers/',hasAttribute:name=>name==='data-reset-filters'};
    b.events.click({target:{closest:()=>link}});
    assert.equal(b.stored()['/customers/'],undefined);
    assert.equal(link.href,'https://app.test/customers/');
});
test('invalid saved query types cannot break rendering or redirect',()=>{
    for(const query of [null,123,{},[], 'https://other.test']) {
        const b=browser({saved:saved({'/customers/':{query}})});
        assert.equal(b.redirects.length,0);
    }
});
