import test from 'node:test';import assert from 'node:assert/strict';
import {pages,sections,labels,restore,transition} from '../rc7_admin/static/workbench/state.mjs';
test('six pages ten sections fully localized',()=>{assert.equal(pages.length,6);assert.equal(sections.length,10);for(const locale of ['zh-CN','en-US']){assert.equal(labels[locale].pages.length,6);assert.equal(labels[locale].sections.length,10);assert.ok(labels[locale].unready);}});
test('invalid saved preferences recover to Chinese without invented scope',()=>{assert.deepEqual(restore({locale:'bad',theme:'bad',page:'../../',section:'publish'}),{locale:'zh-CN',theme:'system',page:'home',section:'overview'});});
test('language and theme retain page and section; unknown mutations rejected',()=>{let s=restore({page:'detail',section:'gates'});s=transition(s,'locale','en-US');s=transition(s,'theme','dark');assert.equal(s.section,'gates');assert.equal(s.page,'detail');assert.throws(()=>transition(s,'scope','foreign'));});
