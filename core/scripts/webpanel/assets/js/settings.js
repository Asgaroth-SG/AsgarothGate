$(document).ready(function () {
    const contentSection = document.querySelector('.content');
    
    if (!contentSection) {
        console.error('Settings: .content element not found');
        return;
    }

    const API_URLS = {
        serverServicesStatus: contentSection.dataset.serverServicesStatusUrl,
        getIp: contentSection.dataset.getIpUrl,
        getAllNodes: contentSection.dataset.getAllNodesUrl,
        addNode: contentSection.dataset.addNodeUrl,
        deleteNode: contentSection.dataset.deleteNodeUrl,
        getAllExtraConfigs: contentSection.dataset.getAllExtraConfigsUrl,
        addExtraConfig: contentSection.dataset.addExtraConfigUrl,
        deleteExtraConfig: contentSection.dataset.deleteExtraConfigUrl,
        // НОВЫЕ URL
        editExtraConfig: contentSection.dataset.editExtraConfigUrl,
        moveExtraConfig: contentSection.dataset.moveExtraConfigUrl,
        
        normalSubGetSubpath: contentSection.dataset.normalSubGetSubpathUrl,
        telegramGetInterval: contentSection.dataset.telegramGetIntervalUrl,
        getIpLimitConfig: contentSection.dataset.getIpLimitConfigUrl,
        normalSubEditSubpath: contentSection.dataset.normalSubEditSubpathUrl,
        setupDecoy: contentSection.dataset.setupDecoyUrl,
        stopDecoy: contentSection.dataset.stopDecoyUrl,
        getDecoyStatus: contentSection.dataset.getDecoyStatusUrl,
        telegramStart: contentSection.dataset.telegramStartUrl,
        telegramStop: contentSection.dataset.telegramStopUrl,
        telegramSetInterval: contentSection.dataset.telegramSetIntervalUrl,
        normalSubStart: contentSection.dataset.normalSubStartUrl,
        normalSubStop: contentSection.dataset.normalSubStopUrl,
        editIp: contentSection.dataset.editIpUrl,
        backup: contentSection.dataset.backupUrl,
        restore: contentSection.dataset.restoreUrl,
        startIpLimit: contentSection.dataset.startIpLimitUrl,
        stopIpLimit: contentSection.dataset.stopIpLimitUrl,
        cleanIpLimit: contentSection.dataset.cleanIpLimitUrl,
        configIpLimit: contentSection.dataset.configIpLimitUrl,
        statusWarp: contentSection.dataset.statusWarpUrl,
        installWarp: contentSection.dataset.installWarpUrl,
        uninstallWarp: contentSection.dataset.uninstallWarpUrl,
        configureWarp: contentSection.dataset.configureWarpUrl,
        xuiGetConfig: contentSection.dataset.xuiGetConfigUrl,
        xuiUpdateConfig: contentSection.dataset.xuiUpdateConfigUrl,
        xuiTestConnection: contentSection.dataset.xuiTestConnectionUrl,
        xuiSyncStatus: contentSection.dataset.xuiSyncStatusUrl,
        xuiSyncUser: contentSection.dataset.xuiSyncUserUrl,
        xuiSyncAll: contentSection.dataset.xuiSyncAllUrl
    };

    initUI();
    fetchDecoyStatus();
    fetchNodes();
    fetchExtraConfigs();

    // --- Перевод ошибок ---
    function translateError(errorMsg) {
        if (!errorMsg) return "Произошла неизвестная ошибка.";
        if (typeof errorMsg !== 'string') return errorMsg;

        const map = {
            "failed with exit code": "Ошибка выполнения системной команды.",
            "No such file or directory": "Файл или каталог не найден.",
            "Permission denied": "Отказано в доступе.",
            "Address already in use": "Порт уже занят.",
            "Connection refused": "Соединение отклонено (служба не запущена?).",
            "timed out": "Время ожидания истекло.",
            "Invalid input": "Неверные входные данные.",
            "already exists": "Уже существует."
        };

        for (const [key, val] of Object.entries(map)) {
            if (errorMsg.includes(key)) return val;
        }
        return errorMsg;
    }

    function escapeHtml(text) {
        var map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        if (text === null || typeof text === 'undefined') {
            return '';
        }
        return String(text).replace(/[&<>"']/g, function (m) { return map[m]; });
    }

    // Вспомогательная функция для извлечения сообщения об ошибке из AJAX ответа
    function extractErrorMessage(xhr, defaultMessage) {
        if (!xhr.responseJSON || !xhr.responseJSON.detail) {
            return defaultMessage;
        }
        
        const detail = xhr.responseJSON.detail;
        if (typeof detail === 'string') {
            return detail;
        } else if (Array.isArray(detail)) {
            return detail.map(err => {
                if (typeof err === 'string') {
                    return err;
                } else if (err.msg) {
                    return err.msg;
                } else {
                    return JSON.stringify(err);
                }
            }).join('; ');
        } else {
            // Если это объект, пытаемся извлечь понятное сообщение
            if (detail.message) {
                return detail.message;
            } else if (detail.error) {
                return detail.error;
            } else {
                return JSON.stringify(detail);
            }
        }
    }

    function isValidURI(uri) {
        if (!uri) return false;
        const lowerUri = uri.toLowerCase();
        return lowerUri.startsWith("vmess://") || lowerUri.startsWith("vless://") || lowerUri.startsWith("ss://") || lowerUri.startsWith("trojan://");
    }

    function isValidPath(path) {
        if (!path) return false;
        return path.trim() !== '';
    }

    function isValidDomain(domain) {
        if (!domain) return false;
        const lowerDomain = domain.toLowerCase();
        if (lowerDomain.startsWith("http://") || lowerDomain.startsWith("https://")) return false;
        const ipV4Regex = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
        if (ipV4Regex.test(domain)) return false;
        const domainRegex = /^(?!-)(?:[a-zA-Z\d-]{0,62}[a-zA-Z\d]\.){1,126}(?!\d+$)[a-zA-Z\d]{1,63}$/;
        return domainRegex.test(lowerDomain);
    }

    function isValidPort(port) {
        if (!port) return false;
        return /^[0-9]+$/.test(port) && parseInt(port) > 0 && parseInt(port) <= 65535;
    }

    function isValidSha256Pin(pin) {
        if (!pin) return false;
        const pinRegex = /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/i;
        return pinRegex.test(pin.trim());
    }

    function isValidSubPath(subpath) {
        if (!subpath) return false;
        return /^[a-zA-Z0-9]+$/.test(subpath);
    }

    function isValidIPorDomain(input) {
        if (input === null || typeof input === 'undefined') return false;
        input = input.trim();
        if (input === '') return false;

        const ipV4Regex = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
        const ipV6Regex = /^(([0-9a-fA-F]{1,4}:){7,7}([0-9a-fA-F]{1,4}|:)|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$/;
        const domainRegex = /^(?!-)(?:[a-zA-Z\d-]{0,62}[a-zA-Z\d]\.){1,126}(?!\d+$)[a-zA-Z\d]{1,63}$/;
        const lowerInput = input.toLowerCase();

        return ipV4Regex.test(input) || ipV6Regex.test(input) || domainRegex.test(lowerInput);
    }

    function isValidPositiveNumber(value) {
        if (!value) return false;
        return /^[0-9]+$/.test(value) && parseInt(value) > 0;
    }

    function confirmAction(actionName, callback) {
        Swal.fire({
            title: `Вы уверены?`,
            text: `Вы действительно хотите ${actionName}?`,
            icon: "warning",
            showCancelButton: true,
            confirmButtonColor: "#3085d6",
            cancelButtonColor: "#d33",
            confirmButtonText: "Да, выполнить!",
            cancelButtonText: "Отмена"
        }).then((result) => {
            if (result.isConfirmed) {
                callback();
            }
        });
    }

    function sendRequest(url, type, data, successMessage, buttonSelector, showReload = true, postSuccessCallback = null) {
        $.ajax({
            url: url,
            type: type,
            contentType: "application/json",
            data: data ? JSON.stringify(data) : null,
            beforeSend: function () {
                if (buttonSelector) {
                    $(buttonSelector).prop('disabled', true);
                    $(buttonSelector + ' .spinner-border').show();
                }
            },
            success: function (response) {
                if (window.showToast) {
                    if (successMessage) showToast("success", "Успешно!", successMessage);
                    // Keep previous behaviour: auto-reload by default
                    if (showReload) {
                        setTimeout(() => location.reload(), 800);
                    } else if (postSuccessCallback) {
                        postSuccessCallback(response);
                    }
                } else {
                    if (successMessage) {
                        Swal.fire("Успешно!", successMessage, "success").then(() => {
                            if (showReload) {
                                location.reload();
                            } else {
                                if (postSuccessCallback) {
                                    postSuccessCallback(response);
                                }
                            }
                        });
                    } else if (postSuccessCallback) {
                        postSuccessCallback(response);
                    }
                }
            },
            error: function (xhr, status, error) {
                let errorMessage = "Произошла непредвиденная ошибка.";
                if (xhr.responseJSON && xhr.responseJSON.detail) {
                    const detail = xhr.responseJSON.detail;
                    if (Array.isArray(detail)) {
                        errorMessage = detail.map(err => `Ошибка в '${err.loc[1]}': ${err.msg}`).join('\n');
                    } else if (typeof detail === 'string') {
                        let userMessage = detail;
                        const failMarker = 'failed with exit code';
                        const markerIndex = detail.indexOf(failMarker);
                        if (markerIndex > -1) {
                            const colonIndex = detail.indexOf(':', markerIndex);
                            if (colonIndex > -1) {
                                userMessage = detail.substring(colonIndex + 1).trim();
                            }
                        }
                        errorMessage = userMessage;
                    }
                }
                if (window.showToast) { showToast("error", "Ошибка!", translateError(errorMessage), { timer: 5000 }); } else { Swal.fire("Ошибка!", translateError(errorMessage), "error"); }
                console.error("AJAX Error:", status, error, xhr.responseText);
            },
            complete: function () {
                if (buttonSelector) {
                    $(buttonSelector).prop('disabled', false);
                    $(buttonSelector + ' .spinner-border').hide();
                }
            }
        });
    }

    function validateForm(formId) {
        let isValid = true;
        $(`#${formId} .form-control:visible`).each(function () {
            const input = $(this);
            const id = input.attr('id');
            let fieldValid = true;

            if (id === 'normal_domain' || id === 'decoy_domain') {
                fieldValid = isValidDomain(input.val());
            } else if (id === 'normal_port') {
                fieldValid = isValidPort(input.val());
            } else if (id === 'normal_subpath_input') {
                fieldValid = isValidSubPath(input.val());
            } else if (id === 'ipv4' || id === 'ipv6') {
                fieldValid = (input.val().trim() === '') ? true : isValidIPorDomain(input.val());
            } else if (id === 'node_ip') {
                fieldValid = isValidIPorDomain(input.val());
            } else if (id === 'node_name' || id === 'extra_config_name') {
                fieldValid = input.val().trim() !== "";
            } else if (id === 'extra_config_uri') {
                fieldValid = isValidURI(input.val());
            } else if (id === 'block_duration' || id === 'max_ips' || id === 'telegram_backup_interval') {
                if (input.val().trim() === '' && id === 'telegram_backup_interval') {
                    fieldValid = true;
                } else {
                    fieldValid = isValidPositiveNumber(input.val());
                }
            } else if (id === 'decoy_path') {
                fieldValid = isValidPath(input.val());
            } else if (id === 'node_port') {
                fieldValid = (input.val().trim() === '') ? true : isValidPort(input.val());
            } else if (id === 'node_sni') {
                fieldValid = (input.val().trim() === '') ? true : isValidDomain(input.val());
            } else if (id === 'node_pin') {
                fieldValid = (input.val().trim() === '') ? true : isValidSha256Pin(input.val());
            } else if (id === 'node_obfs') {
                fieldValid = true;
            } else {
                if (input.attr('placeholder') && (input.attr('placeholder').includes('Enter') || input.attr('placeholder').includes('Введите')) && !input.attr('id').startsWith('ipv')) {
                    fieldValid = input.val().trim() !== "";
                }
            }

            if (!fieldValid) {
                input.addClass('is-invalid');
                isValid = false;
            } else {
                input.removeClass('is-invalid');
            }
        });
        return isValid;
    }

    function initUI() {
        $.ajax({
            url: API_URLS.serverServicesStatus,
            type: "GET",
            success: function (data) {
                updateServiceUI(data);
            },
            error: function (xhr, status, error) {
                console.error("Failed to fetch service status:", error, xhr.responseText);
                if (window.showToast) { showToast("error", "Ошибка!", "Не удалось получить статусы служб."); } else { Swal.fire("Ошибка!", "Не удалось получить статусы служб.", "error"); }
            }
        });

        $.ajax({
            url: API_URLS.getIp,
            type: "GET",
            success: function (data) {
                $("#ipv4").val(data.ipv4 || "");
                $("#ipv6").val(data.ipv6 || "");
            },
            error: function (xhr, status, error) {
                console.error("Failed to fetch IP addresses:", error, xhr.responseText);
            }
        });
    }

    function fetchNodes() {
        $.ajax({
            url: API_URLS.getAllNodes,
            type: "GET",
            success: function (nodes) {
                renderNodes(nodes);
            },
            error: function (xhr) {
                if (window.showToast) { showToast("error", "Ошибка!", "Не удалось получить список внешних узлов."); } else { Swal.fire("Ошибка!", "Не удалось получить список внешних узлов.", "error"); }
                console.error("Error fetching nodes:", xhr.responseText);
            }
        });
    }

    function renderNodes(nodes) {
        const tableBody = $("#nodes_table tbody");
        tableBody.empty();

        if (nodes && nodes.length > 0) {
            $("#nodes_table").show();
            $("#no_nodes_message").hide();

            nodes.forEach(node => {
                const rawType = (node.type || node.node_type || 'standard').toString().toLowerCase();
                const isPremium = rawType === 'premium';
                const typeLabel = isPremium ? 'Premium' : 'Standard';
                const typeClass = isPremium ? 'badge badge-premium' : 'badge badge-standard';

                const row = `<tr>
								<td>${escapeHtml(node.name)}</td>
								<td><span class="${typeClass}">${typeLabel}</span></td>
								<td>${escapeHtml(node.ip)}</td>
								<td>${escapeHtml(node.port || 'Н/Д')}</td>
								<td>${escapeHtml(node.sni || 'Н/Д')}</td>
								<td>${escapeHtml(node.obfs || 'Н/Д')}</td>
								<td>${escapeHtml(node.insecure ? 'Да' : 'Нет')}</td>
								<td>${escapeHtml(node.pinSHA256 || 'Н/Д')}</td>
								<td>
									<button class="btn btn-xs btn-danger delete-node-btn" data-name="${escapeHtml(node.name)}">
										<i class="fas fa-trash"></i> Удалить
									</button>
								</td>
							</tr>`;
                tableBody.append(row);
            });
        } else {
            $("#nodes_table").hide();
            $("#no_nodes_message").show();
        }
    }

    function addNode() {
        if (!validateForm('add_node_form')) return;

        const name = $("#node_name").val().trim();
        const ip = $("#node_ip").val().trim();
        const port = $("#node_port").val().trim();
        const sni = $("#node_sni").val().trim();
        const obfs = $("#node_obfs").val().trim();
        const pinSHA256 = $("#node_pin").val().trim();
        const insecure = $("#node_insecure").is(':checked');
        const type = ($("#node_type").val() || 'standard').toLowerCase();
        const data = {
            name: name,
            ip: ip,
            insecure: insecure,
            node_type: type

        };

        if (port) data.port = parseInt(port);
        if (sni) data.sni = sni;
        if (obfs) data.obfs = obfs;
        if (pinSHA256) data.pinSHA256 = pinSHA256;

        confirmAction(`добавить узел '${name}'`, function () {
            sendRequest(
                API_URLS.addNode,
                "POST",
                data,
                `Узел '${name}' успешно добавлен!`,
                "#add_node_btn",
                false,
                function () {
                    $("#add_node_form")[0].reset();
                    $("#add_node_form .form-control").removeClass('is-invalid');
                    fetchNodes();
                }
            );
        });
    }

    function deleteNode(nodeName) {
        confirmAction(`удалить узел '${nodeName}'`, function () {
            sendRequest(
                API_URLS.deleteNode,
                "POST",
                { name: nodeName },
                `Узел '${nodeName}' успешно удален!`,
                null,
                false,
                fetchNodes
            );
        });
    }

    function fetchExtraConfigs() {
        $.ajax({
            url: API_URLS.getAllExtraConfigs,
            type: "GET",
            success: function (configs) {
                renderExtraConfigs(configs);
            },
            error: function (xhr) {
                if (window.showToast) { showToast("error", "Ошибка!", "Не удалось получить дополнительные конфигурации."); } else { Swal.fire("Ошибка!", "Не удалось получить дополнительные конфигурации.", "error"); }
                console.error("Error fetching extra configs:", xhr.responseText);
            }
        });
    }

    function renderExtraConfigs(configs) {
        const tableBody = $("#extra_configs_table tbody");
        tableBody.empty();

        if (configs && configs.length > 0) {
            $("#extra_configs_table").show();
            $("#no_extra_configs_message").hide();

            configs.forEach((config, index) => {
                const rawPlan = (config.plan || config.type || "standard").toString().toLowerCase();
                const isPremium = rawPlan === "premium";
                const planLabel = isPremium ? "Premium" : "Standard";
                const planClass = isPremium ? "badge badge-premium" : "badge badge-standard";
                const uriVal = (config.uri || "").toString();
                const shortUri = uriVal.length > 30 ? uriVal.substring(0, 30) + '...' : uriVal;

                // Кнопки сортировки (скрываем верхнюю для первого, нижнюю для последнего)
                const upBtnStyle = index === 0 ? 'visibility: hidden;' : '';
                const downBtnStyle = index === configs.length - 1 ? 'visibility: hidden;' : '';

                const row = `<tr>
                    <td>${escapeHtml(config.name)}</td>
                    <td><span class="${planClass}">${planLabel}</span></td>
                    <td title="${escapeHtml(uriVal)}" style="font-family: monospace; font-size: 0.85rem;">${escapeHtml(shortUri)}</td>
                    <td class="text-nowrap">
                        <button class="btn btn-xs btn-default move-config-btn" data-name="${escapeHtml(config.name)}" data-dir="up" style="${upBtnStyle}" title="Вверх">
                            <i class="fas fa-arrow-up"></i>
                        </button>
                        <button class="btn btn-xs btn-default move-config-btn" data-name="${escapeHtml(config.name)}" data-dir="down" style="${downBtnStyle}" title="Вниз">
                            <i class="fas fa-arrow-down"></i>
                        </button>
                        <button class="btn btn-xs btn-info edit-config-btn ml-1" 
                            data-name="${escapeHtml(config.name)}" 
                            data-plan="${escapeHtml(rawPlan)}" 
                            data-uri="${escapeHtml(uriVal)}">
                            <i class="fas fa-pen"></i>
                        </button>
                        <button class="btn btn-xs btn-danger delete-extra-config-btn ml-1" data-name="${escapeHtml(config.name)}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
                tableBody.append(row);
            });
        } else {
            $("#extra_configs_table").hide();
            $("#no_extra_configs_message").show();
        }
    }

    function addExtraConfig() {
        if (!validateForm('add_extra_config_form')) return;

        const name = $("#extra_config_name").val().trim();
        const uri = $("#extra_config_uri").val().trim();
        const plan = ($("#extra_config_plan").val() || "standard").toLowerCase();

        confirmAction(`добавить конфигурацию '${name}'`, function () {
            sendRequest(
                API_URLS.addExtraConfig,
                "POST",
                { name: name, uri: uri, plan: plan },
                `Конфигурация '${name}' успешно добавлена!`,
                "#add_extra_config_btn",
                false,
                function () {
                    $("#extra_config_name").val('');
                    $("#extra_config_uri").val('');
                    $("#extra_config_plan").val('standard');
                    $("#add_extra_config_form .form-control").removeClass('is-invalid');
                    fetchExtraConfigs();
                }
            );
        });
    }

    function deleteExtraConfig(configName) {
        confirmAction(`удалить конфигурацию '${configName}'`, function () {
            sendRequest(
                API_URLS.deleteExtraConfig,
                "POST",
                { name: configName },
                `Конфигурация '${configName}' успешно удалена!`,
                null,
                false,
                fetchExtraConfigs
            );
        });
    }

    function updateServiceUI(data) {
        const servicesMap = {
            "hysteria_telegram_bot": "#telegram_form",
            "hysteria_normal_sub": "#normal_sub_service_form",
            "hysteria_iplimit": "#ip-limit-service",
            "hysteria_warp": "#warp_service"
        };

        Object.keys(servicesMap).forEach(serviceKey => {
            let isRunning = data[serviceKey];

            if (serviceKey === "hysteria_telegram_bot") {
                const $form = $("#telegram_form");
                if (isRunning) {
                    $form.find('[data-group="start-only"]').hide();
                    $("#telegram_start").hide();
                    $("#telegram_stop").show();
                    $("#telegram_save_interval").show();
                    if ($form.find(".alert-info").length === 0) {
                        $form.prepend(`<div class='alert alert-info'>Служба работает. Вы можете остановить её или изменить интервал бэкапа.</div>`);
                    }
                    fetchTelegramBackupInterval();
                } else {
                    $form.find('[data-group="start-only"]').show();
                    $("#telegram_start").show();
                    $("#telegram_stop").hide();
                    $("#telegram_save_interval").hide();
                    $form.find(".alert-info").remove();
                    $("#telegram_backup_interval").val("");
                }

            } else if (serviceKey === "hysteria_normal_sub") {
                const $normalForm = $("#normal_sub_service_form");
                const $normalFormGroups = $normalForm.find(".form-group");
                const $normalStartBtn = $("#normal_start");
                const $normalStopBtn = $("#normal_stop");
                const $normalSubConfigTabLi = $(".normal-sub-config-tab-li");

                if (isRunning) {
                    $normalFormGroups.hide();
                    $normalStartBtn.hide();
                    $normalStopBtn.show();
                    if ($normalForm.find(".alert-info").length === 0) {
                        $normalForm.prepend(`<div class='alert alert-info'>Служба подписки работает. Вы можете остановить её или настроить путь.</div>`);
                    }
                    $normalSubConfigTabLi.show();
                    fetchNormalSubPath();
                } else {
                    $normalFormGroups.show();
                    $normalStartBtn.show();
                    $normalStopBtn.hide();
                    $normalForm.find(".alert-info").remove();
                    $normalSubConfigTabLi.hide();
                    if ($('#normal-sub-config-link-tab').hasClass('active')) {
                        $('#normal-tab').tab('show');
                    }
                    $("#normal_subpath_input").val("");
                    $("#normal_subpath_input").removeClass('is-invalid');
                }
            } else if (serviceKey === "hysteria_iplimit") {
                const $ipLimitServiceForm = $("#ip_limit_service_form");
                const $configTabLi = $(".ip-limit-config-tab-li");
                if (isRunning) {
                    $("#ip_limit_start").hide();
                    $("#ip_limit_stop").show();
                    $("#ip_limit_clean").show();
                    $configTabLi.show();
                    fetchIpLimitConfig();
                    if ($ipLimitServiceForm.find(".alert-info").length === 0) {
                        $ipLimitServiceForm.prepend(`<div class='alert alert-info'>Служба IP-Limit работает. Вы можете остановить её при необходимости.</div>`);
                    }
                } else {
                    $("#ip_limit_start").show();
                    $("#ip_limit_stop").hide();
                    $("#ip_limit_clean").hide();
                    $configTabLi.hide();
                    if ($('#ip-limit-config-tab').hasClass('active')) {
                        $('#ip-limit-service-tab').tab('show');
                    }
                    $ipLimitServiceForm.find(".alert-info").remove();
                    $("#block_duration").val("");
                    $("#max_ips").val("");
                    $("#block_duration, #max_ips").removeClass('is-invalid');
                }
            } else if (serviceKey === "hysteria_warp") {
                const isWarpServiceRunning = data[serviceKey];
                if (isWarpServiceRunning) {
                    $("#warp_initial_controls").hide();
                    $("#warp_active_controls").show();
                    fetchWarpFullStatusAndConfig();
                } else {
                    $("#warp_initial_controls").show();
                    $("#warp_active_controls").hide();
                    if ($("#warp_config_form").length > 0) {
                        $("#warp_config_form")[0].reset();
                    }
                }
            }
        });
    }

    function fetchNormalSubPath() {
        $.ajax({
            url: API_URLS.normalSubGetSubpath,
            type: "GET",
            success: function (data) {
                $("#normal_subpath_input").val(data.subpath || "");
                if (data.subpath) {
                    $("#normal_subpath_input").removeClass('is-invalid');
                }
            },
            error: function (xhr, status, error) {
                console.error("Failed to fetch NormalSub subpath:", error, xhr.responseText);
                $("#normal_subpath_input").val("");
            }
        });
    }

    function fetchTelegramBackupInterval() {
        $.ajax({
            url: API_URLS.telegramGetInterval,
            type: "GET",
            success: function (data) {
                if (data.backup_interval) {
                    $("#telegram_backup_interval").val(data.backup_interval);
                } else {
                    $("#telegram_backup_interval").val("");
                }
            },
            error: function (xhr, status, error) {
                console.error("Failed to fetch Telegram backup interval:", error, xhr.responseText);
                $("#telegram_backup_interval").val("");
            }
        });
    }

    function fetchIpLimitConfig() {
        $.ajax({
            url: API_URLS.getIpLimitConfig,
            type: "GET",
            success: function (data) {
                $("#block_duration").val(data.block_duration || "");
                $("#max_ips").val(data.max_ips || "");
                if (data.block_duration) $("#block_duration").removeClass('is-invalid');
                if (data.max_ips) $("#max_ips").removeClass('is-invalid');
            },
            error: function (xhr, status, error) {
                console.error("Failed to fetch IP Limit config:", error, xhr.responseText);
                $("#block_duration").val("");
                $("#max_ips").val("");
            }
        });
    }

    function startTelegram() {
        if (!validateForm('telegram_form')) return;

        const token = $("#telegram_api_token").val().trim();
        const adminId = $("#telegram_admin_id").val().trim();
        const interval = $("#telegram_backup_interval").val().trim();

        const data = { token: token, admin_id: adminId };
        if (interval !== "") data.backup_interval = parseInt(interval);

        confirmAction("запустить Telegram бота", function () {
            sendRequest(
                API_URLS.telegramStart,
                "POST",
                data,
                "Telegram бот успешно запущен!",
                "#telegram_start"
            );
        });
    }

    function stopTelegram() {
        confirmAction("остановить Telegram бота", function () {
            sendRequest(
                API_URLS.telegramStop,
                "POST",
                null,
                "Telegram бот успешно остановлен!",
                "#telegram_stop"
            );
        });
    }

    function saveTelegramInterval() {
        const interval = $("#telegram_backup_interval").val().trim();
        if (interval !== "" && !isValidPositiveNumber(interval)) {
            $("#telegram_backup_interval").addClass('is-invalid');
            return;
        }
        $("#telegram_backup_interval").removeClass('is-invalid');

        const data = {};
        if (interval !== "") data.backup_interval = parseInt(interval);

        confirmAction("сохранить интервал бэкапа Telegram бота", function () {
            sendRequest(
                API_URLS.telegramSetInterval,
                "POST",
                data,
                "Интервал бэкапа успешно сохранён!",
                "#telegram_save_interval",
                false,
                fetchTelegramBackupInterval
            );
        });
    }

    function startNormal() {
        if (!validateForm('normal_sub_service_form')) return;

        const domain = $("#normal_domain").val().trim();
        const port = $("#normal_port").val().trim();

        confirmAction("запустить службу подписок", function () {
            sendRequest(
                API_URLS.normalSubStart,
                "POST",
                { domain: domain, port: parseInt(port) },
                "Служба подписки успешно запущена!",
                "#normal_start"
            );
        });
    }

    function stopNormal() {
        confirmAction("остановить службу подписок", function () {
            sendRequest(
                API_URLS.normalSubStop,
                "POST",
                null,
                "Служба подписки успешно остановлена!",
                "#normal_stop"
            );
        });
    }

    function editNormalSubPath() {
        if (!validateForm('normal_sub_config_form')) return;

        const newSubpath = $("#normal_subpath_input").val().trim();

        confirmAction(`изменить подпуть подписки на '${newSubpath}'`, function () {
            sendRequest(
                API_URLS.normalSubEditSubpath,
                "POST",
                { subpath: newSubpath },
                "Путь подписки успешно обновлён!",
                "#normal_subpath_save_btn"
            );
        });
    }

    function saveIP() {
        if (!validateForm('change_ip_form')) return;

        const ipv4 = $("#ipv4").val().trim();
        const ipv6 = $("#ipv6").val().trim();

        confirmAction("сохранить IP/домен", function () {
            sendRequest(
                API_URLS.editIp,
                "POST",
                { ipv4: ipv4, ipv6: ipv6 },
                "IP/домен успешно сохранены!",
                "#ip_change"
            );
        });
    }

    function downloadBackup() {
        window.location.href = API_URLS.backup;
    }

    function uploadBackup() {
        const fileInput = document.getElementById("backup_file");
        if (!fileInput.files.length) {
            if (window.showToast) { showToast("error", "Ошибка!", "Пожалуйста, выберите файл бэкапа."); } else { Swal.fire("Ошибка!", "Пожалуйста, выберите файл бэкапа.", "error"); }
            return;
        }

        const file = fileInput.files[0];
        const formData = new FormData();
        formData.append("file", file);

        Swal.fire({
            title: "Подтвердите",
            text: "Вы уверены, что хотите восстановить из этого бэкапа? Текущие данные будут заменены.",
            icon: "warning",
            showCancelButton: true,
            confirmButtonText: "Да, восстановить",
            cancelButtonText: "Отмена"
        }).then((result) => {
            if (!result.isConfirmed) return;

            $("#upload_backup").prop('disabled', true);
            $("#upload_backup .spinner-border").show();
            $(".progress").show();

            $.ajax({
                url: API_URLS.restore,
                type: "POST",
                data: formData,
                processData: false,
                contentType: false,
                xhr: function () {
                    const xhr = new window.XMLHttpRequest();
                    xhr.upload.addEventListener("progress", function (evt) {
                        if (evt.lengthComputable) {
                            const percentComplete = Math.round((evt.loaded / evt.total) * 100);
                            $("#backup_progress_bar")
                                .css("width", percentComplete + "%")
                                .attr("aria-valuenow", percentComplete)
                                .text(percentComplete + "%");
                        }
                    }, false);
                    return xhr;
                },
                success: function (response) {
                    if (window.showToast) { showToast("success", "Успешно!", "Бэкап успешно восстановлен. Страница будет перезагружена."); setTimeout(() => {
                        location.reload();
                    }, 1200);
                } else {
                    Swal.fire("Успешно!", "Бэкап успешно восстановлен. Страница будет перезагружена.", "success").then(() => {
                        location.reload();
                    });
                }
                },
                error: function (xhr, status, error) {
                    let errorMessage = "Ошибка восстановления бэкапа.";
                    if (xhr.responseJSON && xhr.responseJSON.detail) {
                        errorMessage = translateError(xhr.responseJSON.detail);
                    }
                    if (window.showToast) { showToast("error", "Ошибка!", errorMessage, { timer: 6000 }); } else { Swal.fire("Ошибка!", errorMessage, "error"); }
                },
                complete: function () {
                    $("#upload_backup").prop('disabled', false);
                    $("#upload_backup .spinner-border").hide();
                    $(".progress").hide();
                    $("#backup_progress_bar").css("width", "0%").text("0%");
                    fileInput.value = "";
                }
            });
        });
    }

    function fetchDecoyStatus() {
        $.ajax({
            url: API_URLS.getDecoyStatus,
            type: "GET",
            success: function (data) {
                const messageEl = $("#decoy_status_message");
                if (data.active) {
                    messageEl.html(`<strong>Активно</strong><br>Путь: ${escapeHtml(data.path || 'N/A')}`);
                    $("#decoy_stop").show();
                } else {
                    messageEl.html(`<strong>Не активно</strong>`);
                    $("#decoy_stop").hide();
                }
            },
            error: function () {
                $("#decoy_status_message").text("Не удалось получить статус.");
            }
        });
    }

    function setupDecoy() {
        if (!validateForm('decoy_form')) return;

        const domain = $("#decoy_domain").val().trim();
        const path = $("#decoy_path").val().trim();

        confirmAction("настроить сайт-маскировку", function () {
            sendRequest(
                API_URLS.setupDecoy,
                "POST",
                { domain: domain, decoy_path: path },
                "Сайт-маскировка успешно настроен!",
                "#decoy_setup"
            );
        });
    }

    function stopDecoy() {
        confirmAction("остановить сайт-маскировку", function () {
            sendRequest(
                API_URLS.stopDecoy,
                "POST",
                null,
                "Сайт-маскировка успешно остановлен!",
                "#decoy_stop"
            );
        });
    }

    function startIPLimit() {
        confirmAction("запустить службу IP Limit", function () {
            sendRequest(
                API_URLS.startIpLimit,
                "POST",
                null,
                "Служба IP Limit успешно запущена!",
                "#ip_limit_start"
            );
        });
    }

    function stopIPLimit() {
        confirmAction("остановить службу IP Limit", function () {
            sendRequest(
                API_URLS.stopIpLimit,
                "POST",
                null,
                "Служба IP Limit успешно остановлена!",
                "#ip_limit_stop"
            );
        });
    }

    function cleanIPLimit() {
        confirmAction("очистить базу IP Limit и разблокировать все IP", function () {
            sendRequest(
                API_URLS.cleanIpLimit,
                "POST",
                null,
                "База IP Limit успешно очищена!",
                "#ip_limit_clean",
                true
            );
        });
    }

    function configIPLimit() {
        if (!validateForm('ip_limit_config_form')) return;
        const blockDuration = $("#block_duration").val();
        const maxIps = $("#max_ips").val();
        confirmAction("сохранить конфигурацию IP Limit", function () {
            sendRequest(
                API_URLS.configIpLimit,
                "POST",
                { block_duration: parseInt(blockDuration), max_ips: parseInt(maxIps) },
                "Конфигурация IP Limit успешно сохранена!",
                "#ip_limit_change_config",
                false,
                fetchIpLimitConfig
            );
        });
    }

    function fetchWarpFullStatusAndConfig() {
        $.ajax({
            url: API_URLS.statusWarp,
            type: "GET",
            success: function (data) {
                $("#warp_all_traffic").prop('checked', data.all_traffic_via_warp || false);
                $("#warp_popular_sites").prop('checked', data.popular_sites_via_warp || false);
                $("#warp_domestic_sites").prop('checked', data.domestic_sites_via_warp || false);
                $("#warp_block_adult_sites").prop('checked', data.block_adult_content || false);

                $("#warp_initial_controls").hide();
                $("#warp_active_controls").show();
            },
            error: function (xhr, status, error) {
                let errorMsg = "Не удалось получить конфигурацию WARP.";
                if (xhr.responseJSON && xhr.responseJSON.detail) {
                    errorMsg = translateError(xhr.responseJSON.detail);
                }
                console.error("Error fetching WARP config:", errorMsg, xhr.responseText);

                if (xhr.status === 404) {
                    $("#warp_initial_controls").show();
                    $("#warp_active_controls").hide();
                    if ($("#warp_config_form").length > 0) {
                        $("#warp_config_form")[0].reset();
                    }
                    if (window.showToast) { showToast("info", "Инфо", "Служба WARP возможно не полностью настроена. Попробуйте переустановить, если проблема сохранится.", { timer: 7000 }); } else { Swal.fire("Инфо", "Служба WARP возможно не полностью настроена. Попробуйте переустановить, если проблема сохранится.", "info"); }
                } else {
                    if ($("#warp_config_form").length > 0) {
                        $("#warp_config_form")[0].reset();
                    }
                    if (window.showToast) { showToast("warning", "Внимание", "Не удалось загрузить текущие настройки WARP. Пожалуйста, проверьте вручную или пересохраните.", { timer: 7000 }); } else { Swal.fire("Внимание", "Не удалось загрузить текущие настройки WARP. Пожалуйста, проверьте вручную или пересохраните.", "warning"); }
                }
            }
        });
    }

    $("#warp_start_btn").on("click", function () {
        confirmAction("установить и запустить WARP", function () {
            sendRequest(
                API_URLS.installWarp,
                "POST",
                null,
                "Запрос на установку WARP отправлен. Страница будет перезагружена.",
                "#warp_start_btn",
                true
            );
        });
    });

    $("#warp_stop_btn").on("click", function () {
        confirmAction("остановить и удалить WARP", function () {
            sendRequest(
                API_URLS.uninstallWarp,
                "DELETE",
                null,
                "Запрос на удаление WARP отправлен. Страница будет перезагружена.",
                "#warp_stop_btn",
                true
            );
        });
    });

    $("#warp_save_config_btn").on("click", function () {
        const configData = {
            all: $("#warp_all_traffic").is(":checked"),
            popular_sites: $("#warp_popular_sites").is(":checked"),
            domestic_sites: $("#warp_domestic_sites").is(":checked"),
            block_adult_sites: $("#warp_block_adult_sites").is(":checked")
        };
        confirmAction("сохранить конфигурацию WARP", function () {
            sendRequest(
                API_URLS.configureWarp,
                "POST",
                configData,
                "Конфигурация WARP успешно сохранена!",
                "#warp_save_config_btn",
                false,
                fetchWarpFullStatusAndConfig
            );
        });
    });
    
    // --- ОБНОВЛЕННЫЕ ОБРАБОТЧИКИ СОБЫТИЙ ДЛЯ EXTRA CONFIG ---

    // Кнопка "Редактировать"
    $("#extra_configs_table").on("click", ".edit-config-btn", function () {
        const name = $(this).data("name");
        const plan = $(this).data("plan");
        const uri = $(this).data("uri");

        $("#edit_config_old_name").val(name);
        $("#edit_config_name").val(name);
        $("#edit_config_plan").val(plan);
        $("#edit_config_uri").val(uri);

        $("#editExtraConfigModal").modal('show');
    });

    // Кнопка "Сохранить" в модальном окне редактирования
    $("#save_edited_config_btn").on("click", function () {
        const oldName = $("#edit_config_old_name").val();
        const newName = $("#edit_config_name").val().trim();
        const plan = $("#edit_config_plan").val();
        const uri = $("#edit_config_uri").val().trim();

        if (!newName || !uri) {
            Swal.fire("Ошибка", "Заполните все поля", "error");
            return;
        }

        sendRequest(
            API_URLS.editExtraConfig,
            "POST",
            { old_name: oldName, new_name: newName, uri: uri, plan: plan },
            "Конфигурация успешно обновлена!",
            "#save_edited_config_btn",
            false,
            function() {
                $("#editExtraConfigModal").modal('hide');
                fetchExtraConfigs();
            }
        );
    });

    // Кнопки "Вверх" / "Вниз"
    $("#extra_configs_table").on("click", ".move-config-btn", function () {
        const name = $(this).data("name");
        const direction = $(this).data("dir");

        sendRequest(
            API_URLS.moveExtraConfig,
            "POST",
            { name: name, direction: direction },
            null, 
            null,
            false, 
            function() {
                fetchExtraConfigs(); // Просто обновляем таблицу без перезагрузки страницы
            }
        );
    });

    // --- КОНЕЦ НОВЫХ ОБРАБОТЧИКОВ ---

    $("#telegram_start").on("click", startTelegram);
    $("#telegram_stop").on("click", stopTelegram);
    $("#telegram_save_interval").on("click", saveTelegramInterval);
    $("#normal_start").on("click", startNormal);
    $("#normal_stop").on("click", stopNormal);
    $("#normal_subpath_save_btn").on("click", editNormalSubPath);
    $("#ip_change").on("click", saveIP);
    $("#download_backup").on("click", downloadBackup);
    $("#upload_backup").on("click", uploadBackup);
    $("#ip_limit_start").on("click", startIPLimit);
    $("#ip_limit_stop").on("click", stopIPLimit);
    $("#ip_limit_clean").on("click", cleanIPLimit);
    $("#ip_limit_change_config").on("click", configIPLimit);
    $("#decoy_setup").on("click", setupDecoy);
    $("#decoy_stop").on("click", stopDecoy);
    $("#add_node_btn").on("click", addNode);
    $("#nodes_table").on("click", ".delete-node-btn", function () {
        const nodeName = $(this).data("name");
        deleteNode(nodeName);
    });
    $("#add_extra_config_btn").on("click", addExtraConfig);
    $("#extra_configs_table").on("click", ".delete-extra-config-btn", function () {
        const configName = $(this).data("name");
        deleteExtraConfig(configName);
    });

    $('#normal_domain, #decoy_domain').on('input', function () {
        if (isValidDomain($(this).val())) {
            $(this).removeClass('is-invalid');
        } else if ($(this).val().trim() !== "") {
            $(this).addClass('is-invalid');
        } else {
            $(this).removeClass('is-invalid');
        }
    });

    $('#normal_port').on('input', function () {
        if (isValidPort($(this).val())) {
            $(this).removeClass('is-invalid');
        } else if ($(this).val().trim() !== "") {
            $(this).addClass('is-invalid');
        } else {
            $(this).removeClass('is-invalid');
        }
    });

    $('#normal_subpath_input').on('input', function () {
        if (isValidSubPath($(this).val())) {
            $(this).removeClass('is-invalid');
        } else if ($(this).val().trim() !== "") {
            $(this).addClass('is-invalid');
        } else {
            $(this).removeClass('is-invalid');
        }
    });

    $('#ipv4, #ipv6, #node_ip').on('input', function () {
        const isLocalIpField = $(this).attr('id') === 'ipv4' || $(this).attr('id') === 'ipv6';
        if (isLocalIpField && $(this).val().trim() === '') {
            $(this).removeClass('is-invalid');
        } else if (isValidIPorDomain($(this).val())) {
            $(this).removeClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });

    $('#node_name, #extra_config_name').on('input', function () {
        if ($(this).val().trim() !== "") {
            $(this).removeClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });

    $('#extra_config_uri').on('input', function () {
        if (isValidURI($(this).val())) {
            $(this).removeClass('is-invalid');
        } else if ($(this).val().trim() !== "") {
            $(this).addClass('is-invalid');
        }
    });

    $('#telegram_api_token, #telegram_admin_id').on('input', function () {
        if ($(this).val().trim() !== "") {
            $(this).removeClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });
    $('#block_duration, #max_ips, #telegram_backup_interval').on('input', function () {
        if ($(this).attr('id') === 'telegram_backup_interval' && $(this).val().trim() === '') {
            $(this).removeClass('is-invalid');
            return;
        }
        if (isValidPositiveNumber($(this).val())) {
            $(this).removeClass('is-invalid');
        } else if ($(this).val().trim() !== "") {
            $(this).addClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });

    $('#decoy_path').on('input', function () {
        if (isValidPath($(this).val())) {
            $(this).removeClass('is-invalid');
        } else if ($(this).val().trim() !== "") {
            $(this).addClass('is-invalid');
        } else {
            $(this).removeClass('is-invalid');
        }
    });

    $('#node_port').on('input', function () {
        const val = $(this).val().trim();
        if (val === '' || isValidPort(val)) {
            $(this).removeClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });

    $('#node_sni').on('input', function () {
        const val = $(this).val().trim();
        if (val === '' || isValidDomain(val)) {
            $(this).removeClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });

    $('#node_pin').on('input', function () {
        const val = $(this).val().trim();
        if (val === '' || isValidSha256Pin(val)) {
            $(this).removeClass('is-invalid');
        } else {
            $(this).addClass('is-invalid');
        }
    });

    // ========== X-UI Integration Management ==========
    
    // Состояния операций (защита от race-condition)
    const xuiOperationStates = {
        testServer: {}, // {serverIndex: {inProgress: bool, requestId: number}}
        saveConfig: { inProgress: false, requestId: null },
        syncNow: { inProgress: false, requestId: null },
        loadLogs: { inProgress: false, requestId: null },
        saveServer: { inProgress: false, requestId: null }
    };

    // Загрузка конфигурации при открытии вкладки
    $('#xui-tab').on('shown.bs.tab', function () {
        // Принудительно загружаем конфигурацию при каждом открытии вкладки
        loadXUIConfig();
        loadXUILastSync();
    });
    
    // Также загружаем при первом открытии страницы, если вкладка уже активна
    if ($('#xui-tab').hasClass('active')) {
        loadXUIConfig();
        loadXUILastSync();
    }
    
    // Дополнительно слушаем событие показа вкладки через Bootstrap
    $('#xui-tab').on('click', function() {
        // Небольшая задержка для гарантии, что вкладка действительно показана
        setTimeout(function() {
            if ($('#xui-tab').hasClass('active')) {
                loadXUIConfig();
                loadXUILastSync();
            }
        }, 100);
    });

    // Переключение типа авторизации в модалке сервера
    $(document).on('change', 'input[name="xui_server_auth_type"]', function () {
        const authType = $(this).val();
        if (authType === 'token') {
            $('#xui_server_username_password_group').hide();
            $('#xui_server_token_group').show();
            $('#xui_server_username, #xui_server_password').removeAttr('required');
            $('#xui_server_token').attr('required', 'required');
        } else {
            $('#xui_server_username_password_group').show();
            $('#xui_server_token_group').hide();
            $('#xui_server_token').removeAttr('required');
            $('#xui_server_username, #xui_server_password').attr('required', 'required');
        }
    });


    // Переключение видимости логов
    $('#xui_toggle_logs_btn').on('click', function () {
        const $content = $('#xui_logs_content');
        const $icon = $(this).find('i');
        if ($content.is(':visible')) {
            $content.slideUp(250);
            $icon.removeClass('fa-chevron-up').addClass('fa-chevron-down');
            $(this).html('<i class="fas fa-chevron-down"></i> Показать');
        } else {
            $content.slideDown(250);
            $icon.removeClass('fa-chevron-down').addClass('fa-chevron-up');
            $(this).html('<i class="fas fa-chevron-up"></i> Скрыть');
        }
    });

    // Проверка валидности серверов для синхронизации
    function hasValidXUIServers(servers) {
        if (!servers || servers.length === 0) {
            return false;
        }
        
        for (const server of servers) {
            if (!server.enabled && server.enabled !== undefined) {
                continue;
            }
            
            const host = (server.host || '').trim();
            if (!host) {
                continue;
            }
            
            const authType = server.auth_type || 'username';
            const password = (server.password || '').trim();
            
            if (authType === 'token') {
                if (password) {
                    return true;
                }
            } else {
                const username = (server.username || '').trim();
                if (username && password) {
                    return true;
                }
            }
        }
        
        return false;
    }

    // Обновление состояния кнопки синхронизации
    function updateSyncButtonState(servers, enabled) {
        const btn = $('#xui_sync_now_btn');
        const isValid = enabled && hasValidXUIServers(servers);
        
        btn.prop('disabled', !isValid);
        
        if (!isValid) {
            if (!enabled) {
                btn.attr('title', 'Включите синхронизацию');
            } else if (!servers || servers.length === 0) {
                btn.attr('title', 'Добавьте хотя бы один сервер');
            } else {
                btn.attr('title', 'Настройте хотя бы один включенный сервер с валидными данными');
            }
        } else {
            btn.removeAttr('title');
        }
    }

    // Загрузка конфигурации X-UI и отображение плиток серверов
    function loadXUIConfig() {
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                const servers = data.xui_servers || [];
                // Отображаем плитки серверов
                renderXUIServers(servers);

                // Заполняем форму синхронизации
                const enabled = data.enabled || false;
                $('#xui_enabled').prop('checked', enabled);
                
                // Обновляем состояние кнопки синхронизации
                updateSyncButtonState(servers, enabled);
                
                // Устанавливаем интервал синхронизации
                $('#xui_sync_interval').val(data.sync_interval || 60);
            },
            error: function (xhr) {
                console.error('Failed to load X-UI config:', xhr);
                const error = extractErrorMessage(xhr, 'Не удалось загрузить конфигурацию X-UI');
                if (window.showToast) {
                    showToast('error', 'Ошибка', error, { timer: 5000 });
                } else {
                    Swal.fire('Ошибка', error, 'error');
                }
            }
        });
    }

    // Отображение плиток серверов
    function renderXUIServers(servers) {
        const grid = $('#xui_servers_grid');
        const noServers = $('#xui_no_servers');
        grid.empty();

        if (!servers || servers.length === 0) {
            grid.hide();
            noServers.show();
            return;
        }

        grid.show();
        noServers.hide();

        servers.forEach((server, index) => {
            const tile = createXUIServerTile(server, index);
            grid.append(tile);
        });
        
        // Инициализируем tooltips для новых кнопок (Bootstrap tooltip)
        // Используем делегирование для tooltip, чтобы избежать конфликтов с кликами
        setTimeout(function() {
            try {
                // Инициализируем только новые tooltip, не трогая существующие
                $('#xui_servers_grid [data-toggle="tooltip"]').each(function() {
                    try {
                        if (!$(this).data('bs.tooltip')) {
                            $(this).tooltip({
                                trigger: 'hover',
                                container: 'body'
                            });
                        }
                    } catch (e) {
                        console.warn('Failed to initialize tooltip:', e);
                    }
                });
            } catch (e) {
                console.warn('Failed to initialize tooltips:', e);
            }
        }, 100);
        
        // Автоматически проверяем статус всех серверов при загрузке
        checkAllServersStatus(servers);
    }
    
    // Автоматическая проверка статуса всех серверов
    function checkAllServersStatus(servers) {
        if (!servers || servers.length === 0) {
            return;
        }
        
        // Проверяем каждый включенный сервер
        servers.forEach((server, index) => {
            // Проверяем только включенные серверы
            if (server.enabled === false) {
                return;
            }
            
            // Небольшая задержка между запросами, чтобы не перегружать сервер
            setTimeout(function() {
                checkServerStatus(index, false); // false = не показывать уведомления
            }, index * 200); // 200ms задержка между каждым запросом
        });
    }
    
    // Проверка статуса одного сервера (с опцией показа уведомлений)
    function checkServerStatus(index, showNotification = true) {
        const state = xuiOperationStates.testServer;
        
        if (!state[index]) {
            state[index] = { inProgress: false, requestId: null };
        }
        
        // Если уже выполняется проверка, пропускаем
        if (state[index].inProgress) {
            return;
        }
        
        state[index].inProgress = true;
        state[index].requestId = Date.now();
        const currentRequestId = state[index].requestId;
        
        const tile = $(`.xui-server-tile[data-server-index="${index}"]`);
        if (!tile.length) {
            state[index].inProgress = false;
            return;
        }
        
        const btn = tile.find('.xui-test-server-btn');
        const statusBadge = tile.find('.badge').first();
        
        // Показываем индикатор загрузки только если это не автоматическая проверка
        if (showNotification) {
            btn.prop('disabled', true);
            btn.find('.spinner-border').show();
            btn.find('.xui-test-icon').hide();
        } else {
            // При автоматической проверке просто показываем индикатор в badge
            statusBadge.html('<i class="fas fa-spinner fa-spin"></i>');
        }
        
        // Формируем URL для проверки здоровья
        const baseUrl = API_URLS.xuiGetConfig.substring(0, API_URLS.xuiGetConfig.lastIndexOf('/api/v1/config/xui'));
        const healthUrl = `${baseUrl}/api/v1/config/xui/server/${index}/health`;
        
        $.ajax({
            url: healthUrl,
            method: 'POST',
            cache: false,
            success: function (data) {
                if (state[index].requestId !== currentRequestId) return;
                
                if (data.healthy) {
                    statusBadge.removeClass('badge-danger badge-secondary').addClass('badge-success').text('Online');
                    if (statusTextContainer.length && !statusTextContainer.find('.badge').length) {
                        statusTextContainer.html(`<span class="badge badge-secondary">${escapeHtml(data.message)}</span>`);
                    } else if (statusTextContainer.length) {
                        statusTextContainer.find('.badge').text(escapeHtml(data.message));
                    }
                } else {
                    statusBadge.removeClass('badge-success badge-secondary').addClass('badge-danger').text('Offline');
                    if (statusTextContainer.length && !statusTextContainer.find('.badge').length) {
                        statusTextContainer.html(`<span class="badge badge-secondary">${escapeHtml(data.message)}</span>`);
                    } else if (statusTextContainer.length) {
                        statusTextContainer.find('.badge').text(escapeHtml(data.message));
                    }
                }
                
                // Показываем уведомление только если это ручная проверка
                if (showNotification && window.showToast) {
                    showToast(data.healthy ? 'success' : 'error', 
                        data.healthy ? 'Успешно' : 'Ошибка', 
                        data.message, 
                        { timer: data.healthy ? 3000 : 5000 });
                }
            },
            error: function (xhr) {
                if (state[index].requestId !== currentRequestId) return;
                const error = extractErrorMessage(xhr, 'Не удалось проверить сервер');
                const statusBadge = tile.find('.badge').first();
                const statusTextContainer = tile.find('.card-text').last();
                statusBadge.removeClass('badge-success badge-secondary').addClass('badge-danger').text('Error');
                if (statusTextContainer.length) {
                    if (!statusTextContainer.find('.badge').length) {
                        statusTextContainer.html(`<span class="badge badge-secondary">${escapeHtml(error)}</span>`);
                    } else {
                        statusTextContainer.find('.badge').text(escapeHtml(error));
                    }
                }
                
                // Показываем уведомление только если это ручная проверка
                if (showNotification && window.showToast) {
                    showToast('error', 'Ошибка', error, { timer: 5000 });
                }
            },
            complete: function () {
                if (state[index].requestId === currentRequestId) {
                    state[index].inProgress = false;
                    state[index].requestId = null;
                    if (showNotification) {
                        btn.prop('disabled', false);
                        btn.find('.spinner-border').hide();
                        btn.find('.xui-test-icon').show();
                    }
                }
            }
        });
    }

    // Создание плитки сервера
    function createXUIServerTile(server, index) {
        const name = escapeHtml(server.name || server.host || `Сервер ${index + 1}`);
        const host = escapeHtml(server.host || '');
        const status = server.status || 'unknown';
        const statusText = server.status_text || '';
        const statusClass = status === 'online' ? 'success' : status === 'offline' ? 'danger' : 'secondary';
        const statusLabel = status === 'online' ? 'Online' : status === 'offline' ? 'Offline' : 'Unknown';
        const enabled = server.enabled !== false;

        return $(`
            <div class="col-md-6 col-lg-4 mb-3">
                <div class="card xui-server-tile ${enabled ? '' : 'bg-light'}" data-server-index="${index}">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <h6 class="card-title mb-0">${name}</h6>
                            <span class="badge badge-${statusClass}">${statusLabel}</span>
                        </div>
                        <p class="card-text text-muted small mb-2">${host}</p>
                        ${statusText ? `<p class="card-text small mb-2"><span class="badge badge-secondary">${escapeHtml(statusText)}</span></p>` : ''}
                        <div class="d-flex justify-content-end" style="gap: 0.25rem;">
                            <button type="button" class="btn btn-xs btn-info xui-test-server-btn" data-index="${index}" 
                                    ${!enabled ? 'disabled' : ''} data-toggle="tooltip" data-placement="top" title="Тест" aria-label="Тест">
                                <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true" style="display: none;"></span>
                                <i class="fas fa-plug xui-test-icon"></i>
                            </button>
                            <button type="button" class="btn btn-xs btn-primary xui-edit-server-btn" data-index="${index}" 
                                    data-toggle="tooltip" data-placement="top" title="Редактировать" aria-label="Редактировать">
                                <i class="fas fa-pen"></i>
                            </button>
                            <button type="button" class="btn btn-xs btn-danger xui-delete-server-btn" data-index="${index}" 
                                    data-toggle="tooltip" data-placement="top" title="Удалить" aria-label="Удалить">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `);
    }

    // Загрузка информации о последнем запуске синхронизации
    function loadXUILastSync() {
        $.ajax({
            url: API_URLS.xuiSyncStatus,
            method: 'GET',
            cache: false, // Отключаем кеширование
            success: function (data) {
                const container = $('#xui_last_sync_info');
                if (data.last_sync_time) {
                    const syncTime = new Date(data.last_sync_time);
                    const timeStr = syncTime.toLocaleString('ru-RU');
                    const statusBadge = data.last_sync_status === 'success' 
                        ? '<span class="badge badge-success">Успешно</span>'
                        : data.last_sync_status === 'failed'
                        ? '<span class="badge badge-danger">Ошибка</span>'
                        : '<span class="badge badge-secondary">Неизвестно</span>';
                    
                    container.html(`
                        <p class="mb-1"><strong>Время:</strong> ${timeStr}</p>
                        <p class="mb-1"><strong>Статус:</strong> ${statusBadge}</p>
                        ${data.last_sync_stats ? `
                            <p class="mb-0"><strong>Статистика:</strong> 
                                Синхронизировано: ${data.last_sync_stats.synced || 0}, 
                                Ошибок: ${data.last_sync_stats.failed || 0}
                            </p>
                        ` : ''}
                    `);
                } else {
                    container.html('<p class="text-muted mb-0">Синхронизация еще не выполнялась</p>');
                }
            },
            error: function (xhr) {
                $('#xui_last_sync_info').html('<p class="text-muted mb-0">Не удалось загрузить информацию</p>');
            }
        });
    }

    // Добавление нового сервера
    $('#xui_add_server_btn').on('click', function () {
        $('#xui_server_index').val(-1);
        $('#xuiServerModalLabel').text('Добавить сервер');
        $('#xui_server_form')[0].reset();
        $('#xui_server_auth_username').prop('checked', true);
        $('#xui_server_username_password_group').show();
        $('#xui_server_token_group').hide();
        $('#xui_server_plan_standard, #xui_server_plan_premium').prop('checked', true);
        $('#xui_server_enabled').prop('checked', true);
        $('#xui_server_base_path').val('/');
        $('#xui_server_timeout').val(10);
        $('#xui_server_retries').val(3);
        $('#xui_server_verify_tls').prop('checked', true);
        $('#xuiServerModal').modal('show');
    });

    // Редактирование сервера
    $(document).on('click', '.xui-edit-server-btn', function () {
        const btn = $(this);
        const index = parseInt(btn.data('index'));
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                const server = data.xui_servers[index];
                if (!server) return;

                $('#xui_server_index').val(index);
                $('#xuiServerModalLabel').text('Редактировать сервер');
                $('#xui_server_name').val(server.name || '');
                $('#xui_server_host').val(server.host || '');
                $('#xui_server_base_path').val(server.base_path || '/');
                $('#xui_server_timeout').val(server.timeout || 10);
                $('#xui_server_retries').val(server.max_retries || 3);
                $('#xui_server_verify_tls').prop('checked', server.verify_tls !== false);
                $('#xui_server_enabled').prop('checked', server.enabled !== false);

                const authType = server.auth_type || 'username';
                if (authType === 'token') {
                    $('#xui_server_auth_token').prop('checked', true);
                    $('#xui_server_username_password_group').hide();
                    $('#xui_server_token_group').show();
                    $('#xui_server_token').val(''); // Не показываем токен
                } else {
                    $('#xui_server_auth_username').prop('checked', true);
                    $('#xui_server_username_password_group').show();
                    $('#xui_server_token_group').hide();
                    $('#xui_server_username').val(server.username || '');
                    $('#xui_server_password').val(''); // Не показываем пароль
                }

                const plans = server.plans || ['standard', 'premium'];
                $('#xui_server_plan_standard').prop('checked', plans.includes('standard'));
                $('#xui_server_plan_premium').prop('checked', plans.includes('premium'));

                $('#xuiServerModal').modal('show');
            }
        });
    });

    // Сохранение сервера (из модалки)
    $('#xui_save_server_btn').on('click', function () {
        const state = xuiOperationStates.saveServer;
        if (state.inProgress) {
            if (window.showToast) {
                showToast('warning', 'Внимание', 'Сохранение уже выполняется', { timer: 3000 });
            }
            return;
        }

        // Валидация
        const name = $('#xui_server_name').val().trim();
        const host = $('#xui_server_host').val().trim();
        const authType = $('input[name="xui_server_auth_type"]:checked').val();
        let username = '', password = '';

        if (!name) {
            if (window.showToast) {
                showToast('error', 'Ошибка', 'Укажите имя сервера', { timer: 4000 });
            }
            return;
        }

        if (!host) {
            if (window.showToast) {
                showToast('error', 'Ошибка', 'Укажите адрес сервера', { timer: 4000 });
            }
            return;
        }

        if (authType === 'token') {
            password = $('#xui_server_token').val().trim();
            if (!password) {
                if (window.showToast) {
                    showToast('error', 'Ошибка', 'Укажите token', { timer: 4000 });
                }
                return;
            }
            username = 'admin';
        } else {
            username = $('#xui_server_username').val().trim();
            password = $('#xui_server_password').val().trim();
            if (!username || !password) {
                if (window.showToast) {
                    showToast('error', 'Ошибка', 'Укажите имя пользователя и пароль', { timer: 4000 });
                }
                return;
            }
        }

        const plans = [];
        if ($('#xui_server_plan_standard').is(':checked')) plans.push('standard');
        if ($('#xui_server_plan_premium').is(':checked')) plans.push('premium');
        if (plans.length === 0) {
            if (window.showToast) {
                showToast('error', 'Ошибка', 'Выберите хотя бы один план', { timer: 4000 });
            }
            return;
        }

        state.inProgress = true;
        state.requestId = Date.now();
        const currentRequestId = state.requestId;

        const btn = $(this);
        btn.prop('disabled', true);
        btn.find('.spinner-border').show();

        // Загружаем текущую конфигурацию
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                const serverIndex = parseInt($('#xui_server_index').val());
                const newServer = {
                    name: name,
                    host: host,
                    base_path: $('#xui_server_base_path').val().trim() || '/',
                    auth_type: authType,
                    username: authType === 'username' ? username : null,
                    password: password,
                    timeout: parseInt($('#xui_server_timeout').val()) || 10,
                    max_retries: parseInt($('#xui_server_retries').val()) || 3,
                    verify_tls: $('#xui_server_verify_tls').is(':checked'),
                    plans: plans,
                    enabled: $('#xui_server_enabled').is(':checked')
                };

                // Обновляем или добавляем сервер
                if (serverIndex >= 0 && serverIndex < data.xui_servers.length) {
                    // Редактирование: сохраняем пароль если он не изменился (***)
                    const oldServer = data.xui_servers[serverIndex];
                    if (password === '' && oldServer.password && oldServer.password !== '***') {
                        newServer.password = oldServer.password;
                    }
                    data.xui_servers[serverIndex] = newServer;
                } else {
                    // Добавление нового
                    data.xui_servers.push(newServer);
                }
                
                // Убеждаемся, что sync_interval присутствует в конфиге
                if (!data.sync_interval || data.sync_interval < 1) {
                    data.sync_interval = 60;
                }

                // Сохраняем конфигурацию
                $.ajax({
                    url: API_URLS.xuiUpdateConfig,
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify(data),
                    success: function () {
                        if (state.requestId !== currentRequestId) return;
                        $('#xuiServerModal').modal('hide');
                            if (window.showToast) {
                                showToast('success', 'Успешно', 'Сервер сохранен', { timer: 3000 });
                            }
                            loadXUIConfig();
                            // Обновляем состояние кнопки синхронизации после сохранения
                            setTimeout(function() {
                                $.ajax({
                                    url: API_URLS.xuiGetConfig,
                                    method: 'GET',
                                    success: function (data) {
                                        updateSyncButtonState(data.xui_servers || [], $('#xui_enabled').is(':checked'));
                                    }
                                });
                            }, 100);
                    },
                    error: function (xhr) {
                        if (state.requestId !== currentRequestId) return;
                        const error = extractErrorMessage(xhr, 'Не удалось сохранить сервер');
                        if (window.showToast) {
                            showToast('error', 'Ошибка', error, { timer: 5000 });
                        }
                    },
                    complete: function () {
                        if (state.requestId === currentRequestId) {
                            state.inProgress = false;
                            state.requestId = null;
                            btn.prop('disabled', false);
                            btn.find('.spinner-border').hide();
                        }
                    }
                });
            },
            error: function () {
                if (state.requestId === currentRequestId) {
                    state.inProgress = false;
                    state.requestId = null;
                    btn.prop('disabled', false);
                    btn.find('.spinner-border').hide();
                }
                if (window.showToast) {
                    showToast('error', 'Ошибка', 'Не удалось загрузить конфигурацию', { timer: 5000 });
                }
            }
        });
    });

    // Удаление сервера
    $(document).on('click', '.xui-delete-server-btn', function () {
        const btn = $(this);
        const index = parseInt(btn.data('index'));
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                const server = data.xui_servers[index];
                if (!server) return;

                const serverName = server.name || server.host || `Сервер ${index + 1}`;
                confirmAction(`удалить сервер '${serverName}'`, function () {
                    data.xui_servers.splice(index, 1);
                    $.ajax({
                        url: API_URLS.xuiUpdateConfig,
                        method: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify(data),
                        success: function () {
                            if (window.showToast) {
                                showToast('success', 'Успешно', 'Сервер удален', { timer: 3000 });
                            }
                            loadXUIConfig();
                            // Обновляем состояние кнопки синхронизации после удаления
                            setTimeout(function() {
                                $.ajax({
                                    url: API_URLS.xuiGetConfig,
                                    method: 'GET',
                                    success: function (data) {
                                        updateSyncButtonState(data.xui_servers || [], $('#xui_enabled').is(':checked'));
                                    }
                                });
                            }, 100);
                        },
                        error: function (xhr) {
                            const error = extractErrorMessage(xhr, 'Не удалось удалить сервер');
                            if (window.showToast) {
                                showToast('error', 'Ошибка', error, { timer: 5000 });
                            }
                        }
                    });
                });
            }
        });
    });

    // Тестирование сервера (из плитки)
    $(document).on('click', '.xui-test-server-btn', function () {
        const btn = $(this);
        const index = parseInt(btn.data('index'));
        
        // Используем общую функцию проверки статуса с уведомлениями
        checkServerStatus(index, true);
    });


    // Сохранение конфигурации синхронизации
    $('#xui_save_sync_btn').on('click', function () {
        saveXUISyncConfig();
    });

    function saveXUISyncConfig() {
        const state = xuiOperationStates.saveConfig;
        if (state.inProgress) {
            if (window.showToast) {
                showToast('warning', 'Внимание', 'Сохранение уже выполняется', { timer: 3000 });
            }
            return;
        }

        // Собираем данные из формы синхронизации
        const enabled = $('#xui_enabled').is(':checked');
        const syncInterval = parseInt($('#xui_sync_interval').val());

        if (!syncInterval || syncInterval < 1) {
            if (window.showToast) {
                showToast('error', 'Ошибка', 'Укажите корректный интервал (минимум 1 минута)', { timer: 4000 });
            }
            return;
        }

        state.inProgress = true;
        state.requestId = Date.now();
        const currentRequestId = state.requestId;

        const btn = $('#xui_save_sync_btn');
        btn.prop('disabled', true);
        btn.find('.spinner-border').show();

        // Загружаем текущую конфигурацию и обновляем только настройки синхронизации
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                const config = {
                    enabled: enabled,
                    mode: data.mode || 'multi-xui',
                    xui_servers: data.xui_servers || [],
                    inbound_filter: data.inbound_filter || { protocol: 'vless' },
                    sync_interval: syncInterval || 60
                };

                $.ajax({
                    url: API_URLS.xuiUpdateConfig,
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify(config),
                    success: function () {
                        if (state.requestId !== currentRequestId) return;
                        
                        if (window.showToast) {
                            showToast('success', 'Успешно', 'Конфигурация сохранена', { timer: 3000 });
                        }
                        loadXUIConfig();
                        // Обновляем состояние кнопки синхронизации после сохранения настроек
                        setTimeout(function() {
                            $.ajax({
                                url: API_URLS.xuiGetConfig,
                                method: 'GET',
                                success: function (data) {
                                    updateSyncButtonState(data.xui_servers || [], $('#xui_enabled').is(':checked'));
                                }
                            });
                        }, 100);
                    },
                    error: function (xhr) {
                        if (state.requestId !== currentRequestId) return;
                        
                        const error = extractErrorMessage(xhr, 'Не удалось сохранить конфигурацию');
                        if (window.showToast) {
                            showToast('error', 'Ошибка', error, { timer: 5000 });
                        } else {
                            Swal.fire('Ошибка', error, 'error');
                        }
                    },
                    complete: function () {
                        if (state.requestId === currentRequestId) {
                            state.inProgress = false;
                            state.requestId = null;
                            btn.prop('disabled', false);
                            btn.find('.spinner-border').hide();
                        }
                    }
                });
            },
            error: function () {
                if (state.requestId === currentRequestId) {
                    state.inProgress = false;
                    state.requestId = null;
                    btn.prop('disabled', false);
                    btn.find('.spinner-border').hide();
                }
                if (window.showToast) {
                    showToast('error', 'Ошибка', 'Не удалось загрузить конфигурацию', { timer: 5000 });
                }
            }
        });
    }

    // Обновление состояния кнопки при изменении настроек
    $('#xui_enabled').on('change', function () {
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                updateSyncButtonState(data.xui_servers || [], $('#xui_enabled').is(':checked'));
            }
        });
    });

    // Запуск синхронизации сейчас
    $('#xui_sync_now_btn').on('click', function () {
        const state = xuiOperationStates.syncNow;
        if (state.inProgress) {
            if (window.showToast) {
                showToast('warning', 'Внимание', 'Синхронизация уже выполняется', { timer: 3000 });
            }
            return;
        }

        // Проверяем валидность конфигурации перед запуском
        $.ajax({
            url: API_URLS.xuiGetConfig,
            method: 'GET',
            cache: false, // Отключаем кеширование для получения актуальных данных
            success: function (data) {
                const enabled = $('#xui_enabled').is(':checked');
                const servers = data.xui_servers || [];
                
                if (!enabled) {
                    if (window.showToast) {
                        showToast('warning', 'Внимание', 'Включите синхронизацию перед запуском', { timer: 4000 });
                    }
                    return;
                }
                
                if (!hasValidXUIServers(servers)) {
                    if (window.showToast) {
                        showToast('error', 'Ошибка', 'Настройте хотя бы один включенный сервер с валидными данными', { timer: 5000 });
                    }
                    return;
                }
                
                // Запускаем синхронизацию
                runSyncNow();
            },
            error: function () {
                if (window.showToast) {
                    showToast('error', 'Ошибка', 'Не удалось проверить конфигурацию', { timer: 5000 });
                }
            }
        });
    });

    function runSyncNow() {
        const state = xuiOperationStates.syncNow;
        state.inProgress = true;
        state.requestId = Date.now();
        const currentRequestId = state.requestId;

        const btn = $('#xui_sync_now_btn');
        btn.prop('disabled', true);
        btn.find('.spinner-border').show();

        $.ajax({
            url: API_URLS.xuiSyncAll,
            method: 'POST',
            success: function (data) {
                if (state.requestId !== currentRequestId) return;
                
                if (window.showToast) {
                    showToast('success', 'Успешно', data.detail || 'Синхронизация завершена', { timer: 4000 });
                }
                loadXUILastSync();
            },
            error: function (xhr) {
                if (state.requestId !== currentRequestId) return;
                
                let error = 'Не удалось синхронизировать пользователей';
                if (xhr.responseJSON && xhr.responseJSON.detail) {
                    const detail = xhr.responseJSON.detail;
                    if (typeof detail === 'string') {
                        error = detail;
                    } else if (Array.isArray(detail)) {
                        error = detail.map(err => typeof err === 'string' ? err : JSON.stringify(err)).join('; ');
                    } else {
                        error = JSON.stringify(detail);
                    }
                }
                if (window.showToast) {
                    showToast('error', 'Ошибка', error, { timer: 5000 });
                } else {
                    Swal.fire('Ошибка', error, 'error');
                }
            },
            complete: function () {
                if (state.requestId === currentRequestId) {
                    state.inProgress = false;
                    state.requestId = null;
                    // Восстанавливаем состояние кнопки на основе текущей конфигурации
                    $.ajax({
                        url: API_URLS.xuiGetConfig,
                        method: 'GET',
                        success: function (data) {
                            updateSyncButtonState(data.xui_servers || [], $('#xui_enabled').is(':checked'));
                        }
                    });
                    btn.find('.spinner-border').hide();
                }
            }
        });
    }

    // Загрузка логов
    $('#xui_load_logs_btn').on('click', function () {
        const state = xuiOperationStates.loadLogs;
        if (state.inProgress) {
            if (window.showToast) {
                showToast('warning', 'Внимание', 'Логи уже загружаются', { timer: 3000 });
            }
            return;
        }

        state.inProgress = true;
        state.requestId = Date.now();
        const currentRequestId = state.requestId;

        const btn = $(this);
        const lines = parseInt($('#xui_log_lines').val()) || 50;
        btn.prop('disabled', true);
        btn.find('.spinner-border').show();

        // Заглушка - в реальности нужен API endpoint для логов
        setTimeout(function () {
            if (state.requestId !== currentRequestId) return;
            
            $('#xui_logs_display').val('Логи синхронизации\n\n[API endpoint для логов не реализован]');
            state.inProgress = false;
            state.requestId = null;
            btn.prop('disabled', false);
            btn.find('.spinner-border').hide();
        }, 500);
    });

    // Копирование логов
    $('#xui_copy_logs_btn').on('click', function () {
        const logsText = $('#xui_logs_display').val();
        if (!logsText) {
            if (window.showToast) {
                showToast('warning', 'Внимание', 'Сначала загрузите логи', { timer: 3000 });
            }
            return;
        }

        navigator.clipboard.writeText(logsText).then(function () {
            if (window.showToast) {
                showToast('success', 'Успешно', 'Логи скопированы в буфер обмена', { timer: 2000 });
            }
        }).catch(function () {
            // Fallback для старых браузеров
            const textarea = document.createElement('textarea');
            textarea.value = logsText;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            if (window.showToast) {
                showToast('success', 'Успешно', 'Логи скопированы в буфер обмена', { timer: 2000 });
            }
        });
    });
});
