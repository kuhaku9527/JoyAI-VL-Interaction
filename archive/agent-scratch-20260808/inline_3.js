
        (function () {
            var body = document.body;
            var toggle = document.getElementById('sidebarToggle');
            var scrim = document.getElementById('sidebarScrim');
            if (!toggle || !scrim) return;
            function setOpen(open) {
                body.classList.toggle('sidebar-open', open);
                toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            }
            toggle.addEventListener('click', function () {
                setOpen(!body.classList.contains('sidebar-open'));
            });
            scrim.addEventListener('click', function () { setOpen(false); });
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') setOpen(false);
            });
            window.addEventListener('resize', function () {
                if (window.innerWidth >= 1024) setOpen(false);
            });
        })();
        