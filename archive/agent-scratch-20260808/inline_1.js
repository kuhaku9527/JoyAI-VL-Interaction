
        document.title = 'JoyAI VL Live';

        // Initialize Lucide icons immediately when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                lucide.createIcons();
                // Localize static markup (issue #47): Chinese resolved from
                // window.JoyI18n.UI_STRING_MAP, never hardcoded in HTML.
                if (window.JoyI18n && typeof window.JoyI18n.applyUiI18n === 'function') {
                    window.JoyI18n.applyUiI18n(document);
                }
            });
        } else {
            lucide.createIcons();
            if (window.JoyI18n && typeof window.JoyI18n.applyUiI18n === 'function') {
                window.JoyI18n.applyUiI18n(document);
            }
        }
    