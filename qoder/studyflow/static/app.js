(function() {
    'use strict';

    var currentWeeklyMarkdown = '';

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    function showMsg(el, text, type) {
        el.textContent = text;
        el.className = 'form-message ' + type;
        el.classList.remove('hidden');
        setTimeout(function() { el.classList.add('hidden'); }, 4000);
    }

    function apiGet(url) {
        return fetch(url).then(function(r) { return r.json(); });
    }

    function apiPost(url, data) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(function(r) { return r.json(); });
    }

    // Theme
    function initTheme() {
        var saved = localStorage.getItem('studyflow-theme');
        if (saved === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            $('.theme-icon').textContent = '☀️';
        }
        $('#theme-toggle').addEventListener('click', function() {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                $('.theme-icon').textContent = '🌙';
                localStorage.setItem('studyflow-theme', 'light');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                $('.theme-icon').textContent = '☀️';
                localStorage.setItem('studyflow-theme', 'dark');
            }
        });
    }

    // Tabs
    function initTabs() {
        $$('.tab-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var tab = btn.getAttribute('data-tab');
                $$('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
                $$('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
                btn.classList.add('active');
                $('#tab-' + tab).classList.add('active');

                if (tab === 'timeline') loadTimeline();
                if (tab === 'suggest') refreshTopicSelects();
                if (tab === 'weekly') refreshTopicSelects();
            });
        });
    }

    // Record form
    function initRecordForm() {
        var form = $('#record-form');
        var msgEl = $('#form-message');

        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var topic = $('#topic-input').value.trim();
            if (!topic) return;

            var btn = $('#submit-btn');
            btn.disabled = true;
            btn.textContent = '保存中...';

            apiPost('/api/record', {
                topic: topic,
                progress: $('#progress-input').value,
                difficulty: $('#difficulty-input').value,
                next_step: $('#nextstep-input').value,
                notes: $('#notes-input').value
            }).then(function(result) {
                if (result.ok) {
                    showMsg(msgEl, '记录已保存到 PowerContext（scope: ' + result.scope_id.substring(0, 8) + '...）', 'success');
                    form.reset();
                    $('#topic-input').value = topic;
                } else {
                    showMsg(msgEl, '保存失败：' + (result.error || '未知错误'), 'error');
                }
            }).catch(function(err) {
                showMsg(msgEl, '网络错误：' + err.message, 'error');
            }).finally(function() {
                btn.disabled = false;
                btn.textContent = '保存记录';
            });
        });

        // Topic dropdown
        var topicInput = $('#topic-input');
        var dropdown = $('#topic-dropdown');
        var dropdownTimer = null;

        topicInput.addEventListener('input', function() {
            clearTimeout(dropdownTimer);
            dropdownTimer = setTimeout(function() {
                refreshTopicDropdown(dropdown, topicInput.value);
            }, 200);
        });

        topicInput.addEventListener('focus', function() {
            refreshTopicDropdown(dropdown, topicInput.value);
        });

        document.addEventListener('click', function(e) {
            if (!topicInput.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });

        $('#topic-select-btn').addEventListener('click', function() {
            dropdown.classList.toggle('hidden');
            refreshTopicDropdown(dropdown, topicInput.value);
        });

        // Sample buttons
        $$('.btn-sample').forEach(function(btn) {
            btn.addEventListener('click', function() {
                topicInput.value = btn.getAttribute('data-topic');
                dropdown.classList.add('hidden');
            });
        });

        // Seed button
        $('#seed-btn').addEventListener('click', function() {
            var seedMsg = $('#seed-message');
            var btn = $('#seed-btn');
            btn.disabled = true;
            btn.textContent = '加载中...';

            apiPost('/api/seed', {}).then(function(result) {
                if (result.ok) {
                    showMsg(seedMsg, '已加载 ' + result.seeded + ' 条样例数据到 PowerContext，主题：' + result.topics.join('、'), 'success');
                    refreshTopicSelects();
                } else {
                    showMsg(seedMsg, '加载失败：' + (result.error || '未知错误'), 'error');
                }
            }).catch(function(err) {
                showMsg(seedMsg, '网络错误：' + err.message, 'error');
            }).finally(function() {
                btn.disabled = false;
                btn.textContent = '加载样例数据到 PowerContext';
            });
        });
    }

    function refreshTopicDropdown(dropdown, filter) {
        apiGet('/api/topics').then(function(result) {
            dropdown.innerHTML = '';
            if (!result.ok || !result.topics || result.topics.length === 0) {
                var emptyItem = document.createElement('div');
                emptyItem.className = 'topic-dropdown-item';
                emptyItem.style.color = 'var(--text-muted)';
                emptyItem.textContent = '暂无主题';
                dropdown.appendChild(emptyItem);
                dropdown.classList.remove('hidden');
                return;
            }
            var topics = result.topics;
            if (filter) {
                var lowerFilter = filter.toLowerCase();
                topics = topics.filter(function(t) {
                    return t.title.toLowerCase().indexOf(lowerFilter) !== -1;
                });
            }
            if (topics.length === 0) {
                var noMatch = document.createElement('div');
                noMatch.className = 'topic-dropdown-item';
                noMatch.style.color = 'var(--text-muted)';
                noMatch.textContent = '无匹配主题';
                dropdown.appendChild(noMatch);
            } else {
                topics.forEach(function(t) {
                    var item = document.createElement('div');
                    item.className = 'topic-dropdown-item';
                    item.textContent = t.title;
                    item.addEventListener('click', function() {
                        $('#topic-input').value = t.title;
                        dropdown.classList.add('hidden');
                    });
                    dropdown.appendChild(item);
                });
            }
            dropdown.classList.remove('hidden');
        }).catch(function() {
            dropdown.classList.add('hidden');
        });
    }

    // Timeline
    function loadTimeline() {
        var container = $('#timeline-container');
        container.innerHTML = '';
        var loadingDiv = document.createElement('div');
        loadingDiv.className = 'loading-state';
        loadingDiv.textContent = '加载中...';
        container.appendChild(loadingDiv);

        var topicSelect = $('#timeline-topic-select');
        var topic = topicSelect.value;

        if (!topic) {
            apiGet('/api/topics').then(function(result) {
                container.innerHTML = '';
                if (result.ok && result.topics && result.topics.length > 0) {
                    loadTimelineForTopic(result.topics[0].title, container);
                } else {
                    var emptyDiv = document.createElement('div');
                    emptyDiv.className = 'empty-state';
                    emptyDiv.textContent = '暂无学习记录。请先添加记录或加载样例数据。';
                    container.appendChild(emptyDiv);
                }
            }).catch(function(err) {
                container.innerHTML = '';
                var errDiv = document.createElement('div');
                errDiv.className = 'error-state';
                errDiv.textContent = '加载失败：' + err.message;
                container.appendChild(errDiv);
            });
        } else {
            loadTimelineForTopic(topic, container);
        }
    }

    function createTimelineItem(rec) {
        var content = rec.content || {};
        var item = document.createElement('div');
        item.className = 'timeline-item';

        var dateDiv = document.createElement('div');
        dateDiv.className = 'timeline-date';
        dateDiv.textContent = rec.created_at.replace('T', ' ').substring(0, 16);
        item.appendChild(dateDiv);

        var topicDiv = document.createElement('div');
        topicDiv.className = 'timeline-topic';
        topicDiv.textContent = rec.topic;
        item.appendChild(topicDiv);

        var contentDiv = document.createElement('div');
        contentDiv.className = 'timeline-content';
        if (content.progress) {
            var label1 = document.createElement('span');
            label1.className = 'label';
            label1.textContent = '进展：';
            contentDiv.appendChild(label1);
            contentDiv.appendChild(document.createTextNode(content.progress));
            contentDiv.appendChild(document.createElement('br'));
        }
        if (content.difficulty) {
            var label2 = document.createElement('span');
            label2.className = 'label';
            label2.textContent = '困难：';
            contentDiv.appendChild(label2);
            contentDiv.appendChild(document.createTextNode(content.difficulty));
            contentDiv.appendChild(document.createElement('br'));
        }
        if (content.next_step) {
            var label3 = document.createElement('span');
            label3.className = 'label';
            label3.textContent = '下一步：';
            contentDiv.appendChild(label3);
            contentDiv.appendChild(document.createTextNode(content.next_step));
            contentDiv.appendChild(document.createElement('br'));
        }
        if (content.notes) {
            var label4 = document.createElement('span');
            label4.className = 'label';
            label4.textContent = '备注：';
            contentDiv.appendChild(label4);
            contentDiv.appendChild(document.createTextNode(content.notes));
        }
        item.appendChild(contentDiv);

        var memIdDiv = document.createElement('div');
        memIdDiv.className = 'timeline-memory-id';
        memIdDiv.textContent = 'memory_id: ' + rec.memory_id;
        item.appendChild(memIdDiv);

        return item;
    }

    function loadTimelineForTopic(topic, container) {
        apiGet('/api/recall?topic=' + encodeURIComponent(topic)).then(function(result) {
            container.innerHTML = '';
            if (!result.ok) {
                var errDiv = document.createElement('div');
                errDiv.className = 'error-state';
                errDiv.textContent = '加载失败';
                container.appendChild(errDiv);
                return;
            }
            if (!result.records || result.records.length === 0) {
                var emptyDiv = document.createElement('div');
                emptyDiv.className = 'empty-state';
                emptyDiv.textContent = '主题「' + topic + '」暂无记录';
                container.appendChild(emptyDiv);
                return;
            }
            result.records.forEach(function(rec) {
                container.appendChild(createTimelineItem(rec));
            });
        }).catch(function(err) {
            container.innerHTML = '';
            var errDiv = document.createElement('div');
            errDiv.className = 'error-state';
            errDiv.textContent = '加载失败：' + err.message;
            container.appendChild(errDiv);
        });
    }

    // Suggestions
    function initSuggestions() {
        $('#suggest-refresh-btn').addEventListener('click', function() {
            var topic = $('#suggest-topic-select').value;
            if (topic) loadSuggestions(topic);
        });

        $('#suggest-topic-select').addEventListener('change', function() {
            var topic = this.value;
            if (topic) loadSuggestions(topic);
            else {
                var container = $('#suggest-container');
                container.innerHTML = '';
                var emptyDiv = document.createElement('div');
                emptyDiv.className = 'empty-state';
                emptyDiv.textContent = '请选择一个主题查看建议';
                container.appendChild(emptyDiv);
            }
        });
    }

    function loadSuggestions(topic) {
        var container = $('#suggest-container');
        container.innerHTML = '';
        var loadingDiv = document.createElement('div');
        loadingDiv.className = 'loading-state';
        loadingDiv.textContent = '生成建议中...';
        container.appendChild(loadingDiv);

        apiGet('/api/recall?topic=' + encodeURIComponent(topic)).then(function(result) {
            container.innerHTML = '';
            if (!result.ok) {
                var errDiv = document.createElement('div');
                errDiv.className = 'error-state';
                errDiv.textContent = '加载失败';
                container.appendChild(errDiv);
                return;
            }

            if (result.summary) {
                var summaryDiv = document.createElement('div');
                summaryDiv.className = 'suggestion-summary';
                summaryDiv.textContent = result.summary;
                container.appendChild(summaryDiv);
            }

            if (result.suggestions && result.suggestions.length > 0) {
                var ul = document.createElement('ul');
                ul.className = 'suggestion-list';
                result.suggestions.forEach(function(s) {
                    var li = document.createElement('li');
                    li.className = 'suggestion-item';
                    li.textContent = s;
                    ul.appendChild(li);
                });
                container.appendChild(ul);
            } else {
                var emptyDiv = document.createElement('div');
                emptyDiv.className = 'empty-state';
                emptyDiv.textContent = '暂无建议，请先添加学习记录';
                container.appendChild(emptyDiv);
            }

            if (result.records && result.records.length > 0) {
                var citeDiv = document.createElement('div');
                citeDiv.className = 'citation-list';
                var citeH4 = document.createElement('h4');
                citeH4.textContent = '来源引用（' + result.records.length + ' 条 PowerContext 记录）';
                citeDiv.appendChild(citeH4);
                result.records.slice(0, 5).forEach(function(rec) {
                    var citeItem = document.createElement('div');
                    citeItem.className = 'citation-item';
                    citeItem.textContent = 'memory_id: ' + rec.memory_id + ' | ' + rec.created_at.substring(0, 10);
                    citeDiv.appendChild(citeItem);
                });
                container.appendChild(citeDiv);
            }
        }).catch(function(err) {
            container.innerHTML = '';
            var errDiv = document.createElement('div');
            errDiv.className = 'error-state';
            errDiv.textContent = '加载失败：' + err.message;
            container.appendChild(errDiv);
        });
    }

    // Weekly report
    function initWeekly() {
        $('#weekly-generate-btn').addEventListener('click', generateWeekly);
        $('#weekly-download-btn').addEventListener('click', downloadWeekly);
    }

    function generateWeekly() {
        var container = $('#weekly-container');
        container.innerHTML = '';
        var loadingDiv = document.createElement('div');
        loadingDiv.className = 'loading-state';
        loadingDiv.textContent = '生成周报中...';
        container.appendChild(loadingDiv);

        var topic = $('#weekly-topic-select').value;
        var days = $('#weekly-days-select').value;
        var url = '/api/weekly?days=' + days;
        if (topic) url += '&topic=' + encodeURIComponent(topic);

        apiGet(url).then(function(result) {
            currentWeeklyMarkdown = result.markdown || '';
            container.innerHTML = '';
            var pre = document.createElement('pre');
            pre.className = 'weekly-markdown';
            pre.textContent = currentWeeklyMarkdown;
            container.appendChild(pre);
            $('#weekly-download-btn').disabled = !currentWeeklyMarkdown;
        }).catch(function(err) {
            container.innerHTML = '';
            var errDiv = document.createElement('div');
            errDiv.className = 'error-state';
            errDiv.textContent = '生成失败：' + err.message;
            container.appendChild(errDiv);
        });
    }

    function downloadWeekly() {
        if (!currentWeeklyMarkdown) return;
        var blob = new Blob([currentWeeklyMarkdown], { type: 'text/markdown;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'studyflow-weekly-' + new Date().toISOString().slice(0, 10) + '.md';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // Topic select refresh
    function refreshTopicSelects() {
        apiGet('/api/topics').then(function(result) {
            if (!result.ok || !result.topics) return;

            var suggestSelect = $('#suggest-topic-select');
            suggestSelect.innerHTML = '';
            var defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = '请选择主题';
            suggestSelect.appendChild(defaultOpt);
            result.topics.forEach(function(t) {
                var opt = document.createElement('option');
                opt.value = t.title;
                opt.textContent = t.title;
                suggestSelect.appendChild(opt);
            });

            var weeklySelect = $('#weekly-topic-select');
            weeklySelect.innerHTML = '';
            var weeklyDefault = document.createElement('option');
            weeklyDefault.value = '';
            weeklyDefault.textContent = '全部主题';
            weeklySelect.appendChild(weeklyDefault);
            result.topics.forEach(function(t) {
                var opt = document.createElement('option');
                opt.value = t.title;
                opt.textContent = t.title;
                weeklySelect.appendChild(opt);
            });

            var timelineSelect = $('#timeline-topic-select');
            timelineSelect.innerHTML = '';
            var timelineDefault = document.createElement('option');
            timelineDefault.value = '';
            timelineDefault.textContent = '全部主题';
            timelineSelect.appendChild(timelineDefault);
            result.topics.forEach(function(t) {
                var opt = document.createElement('option');
                opt.value = t.title;
                opt.textContent = t.title;
                timelineSelect.appendChild(opt);
            });
            timelineSelect.onchange = function() { loadTimeline(); };
        });
    }

    // Init
    function init() {
        initTheme();
        initTabs();
        initRecordForm();
        initSuggestions();
        initWeekly();
        refreshTopicSelects();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
