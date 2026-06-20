import { useTranslation } from 'react-i18next';

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();

  const toggleLang = async () => {
    const next = i18n.language === 'zh' ? 'en' : 'zh';
    i18n.changeLanguage(next);
    // Also save to backend settings
    try {
      await fetch('/api/settings/general', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: next }),
      });
    } catch (e) {
      console.warn('Failed to save language to backend', e);
    }
  };

  return (
    <button
      onClick={toggleLang}
      className="px-2 py-1 rounded-md border text-xs font-medium hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      style={{
        color: 'var(--color-text-muted)',
        borderColor: 'var(--color-border-dark)',
      }}
      title={i18n.language === 'zh' ? 'Switch to English' : '切换到中文'}
    >
      {i18n.language === 'zh' ? 'EN' : '中'}
    </button>
  );
}
