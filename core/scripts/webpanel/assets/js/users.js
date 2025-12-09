$(function () {
    const contentSection = document.querySelector('.content');
    const SERVICE_STATUS_URL = contentSection.dataset.serviceStatusUrl;
    const BULK_REMOVE_URL = contentSection.dataset.bulkRemoveUrl;
    const REMOVE_USER_URL_TEMPLATE = contentSection.dataset.removeUserUrlTemplate;
    const BULK_ADD_URL = contentSection.dataset.bulkAddUrl;
    const ADD_USER_URL = contentSection.dataset.addUserUrl;
    const EDIT_USER_URL_TEMPLATE = contentSection.dataset.editUserUrlTemplate;
    const RESET_USER_URL_TEMPLATE = contentSection.dataset.resetUserUrlTemplate;
    const USER_URI_URL_TEMPLATE = contentSection.dataset.userUriUrlTemplate;
    const BULK_URI_URL = contentSection.dataset.bulkUriUrl;
    const USERS_BASE_URL = contentSection.dataset.usersBaseUrl;
    const GET_USER_URL_TEMPLATE = contentSection.dataset.getUserUrlTemplate;
    const SEARCH_USERS_URL = contentSection.dataset.searchUrl;

    const usernameRegex = /^[a-zA-Z0-9_]+$/;
    const passwordRegex = /^[a-zA-Z0-9]*$/; 
    
    let cachedUserData = [];
    let searchTimeout = null;

    // --- Настройка компактных уведомлений (Toasts) ---
    const Toast = Swal.mixin({
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 3000,
        timerProgressBar: true,
        didOpen: (toast) => {
            toast.addEventListener('mouseenter', Swal.stopTimer)
            toast.addEventListener('mouseleave', Swal.resumeTimer)
        }
    });

    // --- Вспомогательные функции перевода ---

    function translateError(errorMsg) {
        if (!errorMsg) return "Произошла неизвестная ошибка.";
        if (errorMsg.includes("User already exists")) return "Пользователь с таким именем уже существует.";
        if (errorMsg.includes("Username can only contain")) return "Недопустимые символы в имени пользователя.";
        if (errorMsg.includes("failed with exit code")) return "Ошибка выполнения системной команды.";
        return errorMsg; 
    }

    function translateTable() {
        $('#userTableBody td').each(function() {
            let html = $(this).html();
            if (html.includes('Unlimited')) {
                html = html.replace(/Unlimited/g, '<span class="text-success">Безлимит</span>');
                $(this).html(html);
            }
        });
    }

    // --- Основной функционал ---

    function setCookie(name, value, days) {
        let expires = "";
        if (days) {
            const date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = "; expires=" + date.toUTCString();
        }
        document.cookie = name + "=" + (value || "") + expires + "; path=/";
    }

    function getCookie(name) {
        const nameEQ = name + "=";
        const ca = document.cookie.split(';');
        for (let i = 0; i < ca.length; i++) {
            let c = ca[i];
            while (c.charAt(0) === ' ') c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
        }
        return null;
    }

    function generatePassword(length = 32) {
        const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        let result = '';
        for (let i = 0; i < length; i++) {
            result += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        return result;
    }

    function checkIpLimitServiceStatus() {
        $.getJSON(SERVICE_STATUS_URL)
            .done(data => {
                if (data.hysteria_iplimit === true) {
                    $('.requires-iplimit-service').show();
                }
            })
            .fail(() => console.error('Ошибка получения статуса службы лимита IP.'));
    }

    function highlightSearchResults(query) {
        if (!query) return;
        const safeQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${safeQuery})`, 'gi');

        $('#userTableBody tr.user-main-row').each(function() {
            const $nameCol = $(this).find('td:eq(2) strong');
            if ($nameCol.length) {
                const text = $nameCol.text();
                if (regex.test(text)) {
                    $nameCol.html(text.replace(regex, '<span class="search-highlight">$1</span>'));
                }
            }

            const $noteCol = $(this).find('.note-cell small');
            if ($noteCol.length) {
                const text = $noteCol.text();
                if (regex.test(text)) {
                    $noteCol.html(text.replace(regex, '<span class="search-highlight">$1</span>'));
                }
            }
        });
    }

    function validateUsername(inputElement, errorElement) {
        const username = $(inputElement).val();
        const isValid = usernameRegex.test(username);
        $(errorElement).text(isValid ? "" : "Имя пользователя может содержать только латинские буквы, цифры и нижнее подчеркивание.");
        $(inputElement).closest('form').find('button[type="submit"]').prop('disabled', !isValid);
    }
    
    function validatePassword(inputElement, errorElement) {
        const password = $(inputElement).val();
        const isValid = password === '' || passwordRegex.test(password);
        $(errorElement).text(isValid ? "" : "Пароль содержит недопустимые символы (только латиница и цифры).");
        $('#editSubmitButton').prop('disabled', !isValid);
    }
    
    function refreshUserList() {
        const query = $("#searchInput").val().trim();
        if (query !== "") {
            performSearch();
        } else {
            restoreInitialView();
        }
    }

    function performSearch() {
        const query = $("#searchInput").val().trim();
        const $userTableBody = $("#userTableBody");
        const $paginationContainer = $("#paginationContainer");
        const $userTotalCount = $("#user-total-count");

        $paginationContainer.hide();
        $userTableBody
            .css('opacity', 0.5)
            .html('<tr><td colspan="15" class="text-center p-4"><i class="fas fa-spinner fa-spin"></i> Поиск...</td></tr>');

        $.ajax({
            url: SEARCH_USERS_URL,
            type: 'GET',
            data: { q: query },
            success: function (data) {
                $userTableBody.html(data);
                checkIpLimitServiceStatus();
                const resultCount = $userTableBody.find('tr.user-main-row').length;
                $userTotalCount.text(resultCount);
                
                translateTable();
                highlightSearchResults(query);
            },
            error: function () {
                Toast.fire({icon: 'error', title: "Произошла ошибка во время поиска."});
                $userTableBody.html('<tr><td colspan="15" class="text-center p-4 text-danger">Не удалось загрузить результаты поиска.</td></tr>');
            },
            complete: function () {
                $userTableBody.css('opacity', 1);
            }
        });
    }

    function restoreInitialView() {
        const $userTableBody = $("#userTableBody");
        const $paginationContainer = $("#paginationContainer");
        const $userTotalCount = $("#user-total-count");

        $userTableBody
            .css('opacity', 0.5)
            .html('<tr><td colspan="15" class="text-center p-4"><i class="fas fa-spinner fa-spin"></i> Загрузка пользователей...</td></tr>');

        $.ajax({
            url: USERS_BASE_URL,
            type: 'GET',
            success: function (data) {
                const newBody = $(data).find('#userTableBody').html();
                const newPagination = $(data).find('#paginationContainer').html();
                const newTotalCount = $(data).find('#user-total-count').text();

                $userTableBody.html(newBody);
                $paginationContainer.html(newPagination).show();
                $userTotalCount.text(newTotalCount);

                checkIpLimitServiceStatus();
                translateTable(); 
            },
            error: function () {
                Toast.fire({icon: 'error', title: "Не удалось восстановить список пользователей."});
                $userTableBody.html('<tr><td colspan="15" class="text-center p-4 text-danger">Не удалось загрузить пользователей. Пожалуйста, обновите страницу.</td></tr>');
            },
            complete: function () {
                $userTableBody.css('opacity', 1);
            }
        });
    }
    
    $('#editPassword').on('input', function() {
        validatePassword(this, '#editPasswordError');
    });

    $('#addUsername, #addBulkPrefix').on('input', function() {
        validateUsername(this, `#${this.id}Error`);
    });

    $('#addUnlimited').on('change', function() {
        $('#addMaxIps').prop('disabled', this.checked);
    });

    $('#addBulkUnlimited').on('change', function() {
        $('#addBulkMaxIps').prop('disabled', this.checked);
    });

    $('#editUnlimitedIp').on('change', function() {
        $('#editMaxIps').prop('disabled', this.checked);
    });

    $(".filter-button").on("click", function (e) {
        e.preventDefault();
        const filter = $(this).data("filter");
        $("#selectAll").prop("checked", false);
        $("#userTable tbody tr.user-main-row").each(function () {
            let showRow;
            switch (filter) {
                case "on-hold":    
                    showRow = $(this).find("td:eq(3) .badge-warning").length > 0; 
                    break;
                case "online":
                    showRow = $(this).find("td:eq(3) .badge-success").length > 0;
                    break;
                case "disable":
                    showRow = $(this).find("td:eq(8) i").hasClass("text-danger");
                    break;
                default:
                    showRow = true;
            }
            $(this).toggle(showRow).find(".user-checkbox").prop("checked", false);
            if (!showRow) {
                $(this).next('tr.user-details-row').hide();
            }
        });
        
        $(".filter-button").removeClass("active");
        $(this).addClass("active");
    });

    $("#selectAll").on("change", function () {
        $("#userTable tbody tr.user-main-row:visible .user-checkbox").prop("checked", this.checked);
    });

    $("#deleteSelected").on("click", function () {
        const selectedUsers = $(".user-checkbox:checked").map((_, el) => $(el).val()).get();
        if (selectedUsers.length === 0) {
            return Swal.fire("Внимание!", "Пожалуйста, выберите хотя бы одного пользователя для удаления.", "warning");
        }
        Swal.fire({
            title: "Вы уверены?",
            html: `Будут удалены: <b>${selectedUsers.join(", ")}</b>.<br>Это действие нельзя отменить!`,
            icon: "warning",
            showCancelButton: true,
            confirmButtonColor: "#d33",
            confirmButtonText: "Да, удалить их!",
            cancelButtonText: "Отмена"
        }).then((result) => {
            if (!result.isConfirmed) return;

            Swal.fire({
                title: 'Удаление...',
                text: 'Пожалуйста, подождите',
                allowOutsideClick: false,
                didOpen: () => Swal.showLoading()
            });

            if (selectedUsers.length > 1) {
                $.ajax({
                    url: BULK_REMOVE_URL,
                    method: "POST",
                    contentType: "application/json",
                    data: JSON.stringify({ usernames: selectedUsers })
                })
                .done(() => {
                    Swal.close();
                    Toast.fire({icon: 'success', title: "Выбранные пользователи удалены."});
                    refreshUserList();
                })
                .fail((err) => Swal.fire("Ошибка!", translateError(err.responseJSON?.detail), "error"));
            } else {
                const singleUrl = REMOVE_USER_URL_TEMPLATE.replace('U', selectedUsers[0]);
                $.ajax({
                    url: singleUrl,
                    method: "DELETE"
                })
                .done(() => {
                    Swal.close();
                    Toast.fire({icon: 'success', title: `Пользователь ${selectedUsers[0]} удален.`});
                    refreshUserList();
                })
                .fail((err) => Swal.fire("Ошибка!", translateError(err.responseJSON?.detail), "error"));
            }
        });
    });

    $("#addUserForm, #addBulkUsersForm").on("submit", function (e) {
        e.preventDefault();
        const form = $(this);
        const isBulk = form.attr('id') === 'addBulkUsersForm';
        const url = isBulk ? BULK_ADD_URL : ADD_USER_URL;
        const button = form.find('button[type="submit"]').prop('disabled', true);
        
        const formData = new FormData(this);
        const jsonData = Object.fromEntries(formData.entries());

        jsonData.unlimited = jsonData.unlimited === 'on';

        let maxIpsVal;
        if (isBulk) {
            maxIpsVal = $("#addBulkMaxIps").val();
        } else {
            maxIpsVal = $("#addMaxIps").val();
        }
        jsonData.max_ips = maxIpsVal ? parseInt(maxIpsVal) : 0;

        Swal.fire({
            title: 'Добавление...',
            text: 'Пожалуйста, подождите',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        $.ajax({
            url: url,
            method: "POST",
            contentType: "application/json",
            data: JSON.stringify(jsonData),
        })
        .done(res => {
            $('#addUserModal').modal('hide');
            Swal.close();
            
            let successMsg = "";
            if (isBulk) {
                const count = $("#addBulkCount").val();
                successMsg = `Создано ${count} пользователей.`;
            } else {
                const username = $("#addUsername").val();
                successMsg = `Пользователь ${username} создан.`;
            }
            Toast.fire({icon: 'success', title: successMsg});
            refreshUserList();
        })
        .fail(err => Swal.fire("Ошибка!", translateError(err.responseJSON?.detail), "error"))
        .always(() => button.prop('disabled', false));
    });

    $("#editUserModal").on("show.bs.modal", function (event) {
        const user = $(event.relatedTarget).data("user");
        const dataRow = $(event.relatedTarget).closest("tr.user-main-row");
        const url = GET_USER_URL_TEMPLATE.replace('U', user);

        const trafficText = dataRow.find("td:eq(4)").text();
        const expiryText = dataRow.find("td:eq(6)").text().trim();
        const note = dataRow.data('note');
        const statusText = dataRow.find("td:eq(3)").text().trim();
        
        $('#editPasswordError').text('');
        $('#editSubmitButton').prop('disabled', false);

        $("#originalUsername").val(user);
        $("#editUsername").val(user);
        
        let trafficVal = parseFloat(trafficText.split('/')[1]);
        if (isNaN(trafficVal)) trafficVal = 0;
        $("#editTrafficLimit").val(trafficVal);

        if (statusText.includes("On-hold") || statusText.includes("В ожидании") || statusText.includes("Пауза")) {
            $("#editExpirationDays").val('').attr("placeholder", "В ожидании");
        } else {
            let days = parseInt(expiryText);
            if (isNaN(days)) days = 0; 
            $("#editExpirationDays").val(days).attr("placeholder", "");
        }
        
        $("#editNote").val(note || '');
        $("#editBlocked").prop("checked", !dataRow.find("td:eq(8) i").hasClass("text-success"));
        
        const isUnlimited = dataRow.find(".requires-iplimit-service .badge-primary").length > 0;
        $("#editUnlimitedIp").prop("checked", isUnlimited);
        $('#editMaxIps').prop('disabled', isUnlimited);
    
        const passwordInput = $("#editPassword");
        passwordInput.val("").attr("placeholder", "Загрузка..."); 
    
        $.getJSON(url)
            .done(userData => {
                passwordInput.val(userData.password || '').attr("placeholder", "Пусто = не менять");
                $("#editMaxIps").val(userData.max_ips || 0);
                
                if (userData.max_download_bytes) {
                     $("#editTrafficLimit").val((userData.max_download_bytes / (1024*1024*1024)).toFixed(2));
                }

                // подставляем тариф пользователя в селект
                const plan = (userData.plan || 'standard').toLowerCase();
                $("#editPlan").val(plan);

                validatePassword('#editPassword', '#editPasswordError');
            })
            .fail(() => {
                passwordInput.val("").attr("placeholder", "Не удалось загрузить данные");
            });
    });
    
    $('#editUserModal').on('click', '#generatePasswordBtn', function() {
        $('#editPassword').val(generatePassword()).trigger('input');
    });
    
    $("#editUserForm").on("submit", function (e) {
        e.preventDefault();
        const button = $("#editSubmitButton").prop("disabled", true);
        const originalUsername = $("#originalUsername").val();
        const url = EDIT_USER_URL_TEMPLATE.replace('U', originalUsername);

        const formData = new FormData(this);
        const jsonData = Object.fromEntries(formData.entries());
        jsonData.blocked = jsonData.blocked === 'on';
        jsonData.unlimited_ip = jsonData.unlimited_ip === 'on';
        
        const maxIpsVal = $("#editMaxIps").val();
        jsonData.max_ips = maxIpsVal ? parseInt(maxIpsVal) : 0;

        Swal.fire({
            title: 'Обновление...',
            text: 'Пожалуйста, подождите',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        $.ajax({
            url: url,
            method: "PATCH",
            contentType: "application/json",
            data: JSON.stringify(jsonData),
        })
        .done(res => {
            $('#editUserModal').modal('hide');
            Swal.close();
            Toast.fire({icon: 'success', title: `Данные пользователя ${originalUsername} обновлены.`});
            refreshUserList();
        })
        .fail(err => Swal.fire("Ошибка!", translateError(err.responseJSON?.detail), "error"))
        .always(() => button.prop('disabled', false));
    });

    $("#userTable").on("click", ".reset-user, .delete-user", function () {
        const button = $(this);
               const username = button.data("user");
        const isDelete = button.hasClass("delete-user");
        
        const actionRus = isDelete ? "удалить" : "сбросить";
        const actionProcessRus = isDelete ? "Удаление..." : "Сброс...";
        const actionButtonRus = isDelete ? "Да, удалить!" : "Да, сбросить!";
        
        const urlTemplate = isDelete ? REMOVE_USER_URL_TEMPLATE : RESET_USER_URL_TEMPLATE;

        Swal.fire({
            title: `Вы уверены, что хотите ${actionRus}?`,
            html: `Это действие ${actionRus} пользователя <b>${username}</b>.`,
            icon: "warning",
            showCancelButton: true,
            confirmButtonColor: "#d33",
            confirmButtonText: actionButtonRus,
            cancelButtonText: "Отмена"
        }).then((result) => {
            if (!result.isConfirmed) return;

            Swal.fire({
                title: actionProcessRus,
                text: 'Пожалуйста, подождите',
                allowOutsideClick: false,
                didOpen: () => Swal.showLoading()
            });

            $.ajax({
                url: urlTemplate.replace("U", encodeURIComponent(username)),
                method: isDelete ? "DELETE" : "GET",
            })
            .done(res => {
                Swal.close();
                const msg = isDelete 
                    ? `Пользователь ${username} удален.` 
                    : `Пользователь ${username} сброшен.`;
                Toast.fire({icon: 'success', title: msg});
                refreshUserList();
            })
            .fail(() => Swal.fire("Ошибка!", `Не удалось ${actionRus} пользователя.`, "error"));
        });
    });

    $("#qrcodeModal").on("show.bs.modal", function (event) {
        const username = $(event.relatedTarget).data("username");
        const qrcodesContainer = $("#qrcodesContainer").empty();
        const url = USER_URI_URL_TEMPLATE.replace("U", encodeURIComponent(username));
        
        qrcodesContainer.html('<div class="text-center"><i class="fas fa-spinner fa-spin fa-2x"></i></div>');

        $.getJSON(url, response => {
            qrcodesContainer.empty();
            [
                { type: "Копировать ссылку подписки", link: response.normal_sub }
            ].forEach(config => {
                if (!config.link) return;
                const qrId = `qrcode-${config.type.replace(/\s+/g, '')}`;
                const card = $(`<div class="card d-inline-block m-2"><div class="card-body"><div id="${qrId}" class="mx-auto" style="cursor: pointer;"></div><div class="mt-2 text-center small text-body font-weight-bold">${config.type}</div></div></div>`);
                qrcodesContainer.append(card);
                new QRCodeStyling({ width: 200, height: 200, data: config.link, margin: 2 }).append(document.getElementById(qrId));
                card.on("click", () => navigator.clipboard.writeText(config.link).then(() => {
                    Toast.fire({icon: 'success', title: `Ссылка скопирована!`});
                }));
            });
            if (qrcodesContainer.is(':empty')) {
                qrcodesContainer.html('<p class="text-danger">Ссылки не найдены.</p>');
            }
        }).fail(() => {
            qrcodesContainer.html('<p class="text-danger">Ошибка загрузки.</p>');
            Toast.fire({icon: 'error', title: "Не удалось получить конфигурацию."});
        });
    });
    
    $("#showSelectedLinks").on("click", function () {
        const selectedUsers = $(".user-checkbox:checked").map((_, el) => $(el).val()).get();
        if (selectedUsers.length === 0) {
            return Swal.fire("Внимание!", "Пожалуйста, выберите хотя бы одного пользователя.", "warning");
        }

        Swal.fire({ title: 'Получение ссылок...', text: 'Пожалуйста, подождите.', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
        
        $.ajax({
            url: BULK_URI_URL,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ usernames: selectedUsers }),
        }).done(results => {
            Swal.close();
            cachedUserData = results;
            
            const fetchedCount = results.length;
            if (fetchedCount > 0) {
                const hasIPv4 = cachedUserData.some(user => user.ipv4);
                const hasIPv6 = cachedUserData.some(user => user.ipv6);
                const hasNormalSub = cachedUserData.some(user => user.normal_sub);
                const hasNodes = cachedUserData.some(user => user.nodes && user.nodes.length > 0);

                $("#extractIPv4").closest('.form-check-inline').toggle(hasIPv4);
                $("#extractIPv6").closest('.form-check-inline').toggle(hasIPv6);
                $("#extractNormalSub").closest('.form-check-inline').toggle(hasNormalSub);
                $("#extractNodes").closest('.form-check-inline').toggle(hasNodes);

                $("#linksTextarea").val('');
                $("#showLinksModal").modal("show");
            } else {
               Toast.fire({icon: 'error', title: "Не удалось получить информацию."});
            }
        }).fail(() => Swal.fire('Ошибка!', 'Произошла ошибка при получении ссылок.', 'error'));
    });

    $("#extractLinksButton").on("click", function () {
        const allLinks = [];
        const linkTypes = {
            ipv4: $("#extractIPv4").is(":checked"),
            ipv6: $("#extractIPv6").is(":checked"),
            normal_sub: $("#extractNormalSub").is(":checked"),
            nodes: $("#extractNodes").is(":checked")
        };

        cachedUserData.forEach(user => {
            if (linkTypes.ipv4 && user.ipv4) allLinks.push(user.ipv4);
            if (linkTypes.ipv6 && user.ipv6) allLinks.push(user.ipv6);
            if (linkTypes.normal_sub && user.normal_sub) allLinks.push(user.normal_sub);
            if (linkTypes.nodes && user.nodes && user.nodes.length > 0) {
                user.nodes.forEach(node => { if (node.uri) allLinks.push(node.uri); });
            }
        });

        $("#linksTextarea").val(allLinks.join('\n'));
    });
    
    $("#copyExtractedLinksButton").on("click", () => {
        const links = $("#linksTextarea").val();
        if (!links) {
            return Toast.fire({ icon: "info", title: "Нечего копировать!" });
        }
        navigator.clipboard.writeText(links)
            .then(() => Toast.fire({ icon: "success", title: "Ссылки скопированы!" }));
    });

    $('#userTable').on('click', '.toggle-details-btn', function() {
        const $this = $(this);
        const icon = $this.find('i');
        const detailsRow = $this.closest('tr.user-main-row').next('tr.user-details-row');

        detailsRow.toggle();

        if (detailsRow.is(':visible')) {
            icon.removeClass('fa-plus').addClass('fa-minus');
        } else {
            icon.removeClass('fa-minus').addClass('fa-plus');
        }
    });
    
    $('#addUserModal').on('show.bs.modal', function () {
        $('#addUserForm, #addBulkUsersForm').trigger('reset');
        $('#addUsernameError, #addBulkPrefixError').text('');
        
        const singleIpInput = document.getElementById('addMaxIps');
        if (singleIpInput) {
            singleIpInput.value = 0;
            singleIpInput.disabled = false;
        }

        const bulkIpInput = document.getElementById('addBulkMaxIps');
        if (bulkIpInput) {
            bulkIpInput.value = 0;
            bulkIpInput.disabled = false;
        }
        
        Object.assign(document.getElementById('addTrafficLimit'), {value: 30});
        Object.assign(document.getElementById('addExpirationDays'), {value: 30});
        Object.assign(document.getElementById('addBulkTrafficLimit'), {value: 30});
        Object.assign(document.getElementById('addBulkExpirationDays'), {value: 30});
        
        $('#addSubmitButton, #addBulkSubmitButton').prop('disabled', true);
        $('#addUserModal a[data-toggle="tab"]').first().tab('show');
    });

    $("#searchButton").on("click", performSearch);
    $("#searchInput").on("keyup", function (e) {
        clearTimeout(searchTimeout);
        const query = $(this).val().trim();

        if (e.key === 'Enter') {
            performSearch();
            return;
        }
        
        if (query === "") {
            searchTimeout = setTimeout(restoreInitialView, 300);
            return;
        }

        searchTimeout = setTimeout(performSearch, 500);
    });

    function initializeLimitSelector() {
        const savedLimit = getCookie('limit') || '50';
        $('#limit-select').val(savedLimit);

        $('#limit-select').on('change', function() {
            const newLimit = $(this).val();
            setCookie('limit', newLimit, 365);
            window.location.href = USERS_BASE_URL;
        });
    }
    
    initializeLimitSelector();
    checkIpLimitServiceStatus();
    translateTable(); 
    $('[data-toggle="tooltip"]').tooltip();
});
