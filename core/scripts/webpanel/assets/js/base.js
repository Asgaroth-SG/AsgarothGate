$(function () {
    const darkModeToggle = $("#darkModeToggle");
    const darkModeIcon = $("#darkModeIcon");
    const isDarkMode = localStorage.getItem("darkMode") === "enabled";

    setDarkMode(isDarkMode);
    updateIcon(isDarkMode);

    darkModeToggle.on("click", function (e) {
        e.preventDefault();
        const enabled = $("body").hasClass("dark-mode");
        localStorage.setItem("darkMode", enabled ? "disabled" : "enabled");
        setDarkMode(!enabled);
        updateIcon(!enabled);
    });

    function setDarkMode(enabled) {
        $("body").toggleClass("dark-mode", enabled);

        if (enabled) {
            $(".main-header").addClass("navbar-dark").removeClass("navbar-light navbar-white");
            $(".card").addClass("bg-dark");
        } else {
            $(".main-header").addClass("navbar-white navbar-light").removeClass("navbar-dark");
            $(".card").removeClass("bg-dark");
        }
    }

    function updateIcon(enabled) {
        darkModeIcon.removeClass("fa-moon fa-sun")
            .addClass(enabled ? "fa-sun" : "fa-moon");
    }

    const versionUrl = $('body').data('version-url');
    $.ajax({
        url: versionUrl,
        type: 'GET',
        success: function (response) {
             $('#panel-version').text(`Версия: ${response.current_version || 'Н/Д'}`);
        },
        error: function (error) {
            console.error("Error fetching version:", error);
            $('#panel-version').text('Версия: Ошибка');
        }
    });

    function shouldCheckForUpdates() {
        const lastCheck = localStorage.getItem('lastUpdateCheck');
        const updateDismissed = localStorage.getItem('updateDismissed');
        const now = Date.now();
        const checkInterval = 24 * 60 * 60 * 1000;
        
        if (!lastCheck) return true;
        if (updateDismissed && now - parseInt(updateDismissed) < 2 * 60 * 60 * 1000) return false;
        
        return now - parseInt(lastCheck) > checkInterval;
    }

    function showUpdateBar(version, changelog) {
        $('#updateMessage').text(`Доступна версия ${version}`);
        
        const converter = new showdown.Converter();
        const htmlChangelog = changelog ? converter.makeHtml(changelog) : '<p>Список изменений недоступен.</p>';
        $('#changelogText').html(htmlChangelog);

        $('#updateBar').slideDown(300);
        
        $('#viewRelease').off('click').on('click', function(e) {
            e.preventDefault();
            window.open('https://github.com/ReturnFI/Blitz/releases/latest', '_blank');
        });
        
        $('#showChangelog').off('click').on('click', function() {
            const $content = $('#changelogContent');
            const $icon = $(this).find('i');
            
            if ($content.is(':visible')) {
                $content.slideUp(250);
                $icon.removeClass('fa-chevron-up').addClass('fa-chevron-down');
                $(this).css('opacity', '0.8');
            } else {
                $content.slideDown(250);
                $icon.removeClass('fa-chevron-down').addClass('fa-chevron-up');
                $(this).css('opacity', '1');
            }
        });
        
        $('.dropdown-toggle').dropdown();
        
        $('#remindLater').off('click').on('click', function(e) {
            e.preventDefault();
            $('#updateBar').slideUp(350);
        });
        
        $('#skipVersion').off('click').on('click', function(e) {
            e.preventDefault();
            localStorage.setItem('dismissedVersion', version);
            localStorage.setItem('updateDismissed', Date.now().toString());
            $('#updateBar').slideUp(350);
        });
        
        $('#closeUpdateBar').off('click').on('click', function() {
            $('#updateBar').slideUp(350);
        });
    }

    function checkForUpdates() {
        if (!shouldCheckForUpdates()) return;

        const checkVersionUrl = $('body').data('check-version-url');
        $.ajax({
            url: checkVersionUrl,
            type: 'GET',
            timeout: 10000,
            success: function (response) {
                localStorage.setItem('lastUpdateCheck', Date.now().toString());
                
                if (response.is_latest) {
                    localStorage.removeItem('updateDismissed');
                    return;
                }

                const dismissedVersion = localStorage.getItem('dismissedVersion');
                if (dismissedVersion === response.latest_version) return;

                showUpdateBar(response.latest_version, response.changelog);
            },
            error: function (xhr, status, error) {
                if (status !== 'timeout') {
                    console.warn("Update check failed:", error);
                }
                localStorage.setItem('lastUpdateCheck', Date.now().toString());
            }
        });
    }

    setTimeout(checkForUpdates, 2000);
});

// Global toast notifications (SweetAlert2) — unified style across all pages
(function () {
    if (typeof Swal === 'undefined') return;

    // Expose a shared Toast instance so every page uses identical styling
    if (!window.Toast) {
        window.Toast = Swal.mixin({
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 3000,
            timerProgressBar: true,
            didOpen: (toast) => {
                toast.addEventListener('mouseenter', Swal.stopTimer);
                toast.addEventListener('mouseleave', Swal.resumeTimer);
            }
        });
    }

    /**
     * showToast('success'|'error'|'info'|'warning'|'question', 'Title', 'Optional text', {timer, position})
     */
    window.showToast = function (icon, title, text, options) {
        const opts = options || {};
        const payload = Object.assign({}, opts, {
            icon: icon || 'info',
            title: title || '',
        });

        if (text) payload.text = text;

        // Keep the unified default unless explicitly overridden
        if (payload.position == null) payload.position = 'top-end';
        if (payload.timer == null) payload.timer = 3000;
        if (payload.timerProgressBar == null) payload.timerProgressBar = true;
        if (payload.showConfirmButton == null) payload.showConfirmButton = false;

        return (window.Toast || Swal).fire(payload);
    };
})();

