/**
 * 界面语言跟随**全局设置**（Settings → General → Language）。
 *
 * 之前前端只按 localStorage / 浏览器语言猜：设置页里切成中文只影响"当次点击"，
 * 刷新或用另一个标签页又回到英文 —— 而服务端（教程页、导出文档）已经在按全局设置渲染，
 * 于是同一个界面一半中文一半英文。这里把"一个语言"这件事收回一个来源。
 *
 * 顺序：服务端 → localStorage（缓存给下次首帧用）→ 渲染。
 * 服务端读不到时保持现状，绝不清空用户已有的选择。
 */
import i18n from './index';

const LS_KEY = 'langconfig_lang';

function cache(lang: string) {
  try { window.localStorage.setItem(LS_KEY, lang); } catch { /* 隐私模式下写不进去不是错误 */ }
}

/** 读服务端的 general.language。读不到返回空串 —— 调用方保持现状。 */
export async function fetchServerLanguage(): Promise<string> {
  try {
    const r = await fetch('/api/settings/describe', { credentials: 'include' });
    if (!r.ok) return '';
    const data: any = await r.json();
    const gen = (data?.namespaces || []).find((n: any) => n.ns === 'general');
    const lang = String(gen?.value?.language || '').toLowerCase();
    return lang === 'zh' || lang === 'en' ? lang : '';
  } catch {
    return '';
  }
}

/** 首帧之前调用：让第一屏就是设置里的语言。 */
export async function applyServerLanguage(): Promise<string> {
  const lang = await fetchServerLanguage();
  if (!lang) return i18n.language || 'en';
  cache(lang);
  if (i18n.language !== lang) await i18n.changeLanguage(lang);
  return lang;
}

/** 设置页改完语言后（同一标签页/其它标签页）立即生效。 */
export function watchLanguageChanges(): () => void {
  const onUpdated = (e: Event) => {
    const detail = (e as CustomEvent)?.detail || {};
    if (detail.ns !== 'general') return;
    const lang = String(detail.patch?.language || '').toLowerCase();
    if (!lang) return;
    cache(lang);
    if (i18n.language !== lang) void i18n.changeLanguage(lang);
  };
  window.addEventListener('settings:updated', onUpdated as EventListener);
  return () => window.removeEventListener('settings:updated', onUpdated as EventListener);
}
