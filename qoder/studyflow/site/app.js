(function() {
    'use strict';

    var STORAGE_KEY = 'studyflow_demo_records';
    var MARKER = 'studyflow:record';

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    function loadRecords() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
        catch(e) { return []; }
    }
    function saveRecords(records) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
    }
    function genId() {
        return 'demo_' + Date.now().toString(36) + Math.random().toString(36).substring(2, 8);
    }

    // Theme
    function initTheme() {
        var saved = localStorage.getItem('studyflow_site_theme');
        if (saved === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            $('.theme-icon').textContent = '☀️';
        }
        $('#theme-toggle').addEventListener('click', function() {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                $('.theme-icon').textContent = '🌙';
                localStorage.setItem('studyflow_site_theme', 'light');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                $('.theme-icon').textContent = '☀️';
                localStorage.setItem('studyflow_site_theme', 'dark');
            }
        });
    }

    // Tabs
    function initDemoTabs() {
        $$('.demo-tab').forEach(function(tab) {
            tab.addEventListener('click', function() {
                $$('.demo-tab').forEach(function(t) { t.classList.remove('active'); });
                $$('.demo-panel').forEach(function(p) { p.classList.remove('active'); });
                tab.classList.add('active');
                var panel = $('#' + tab.getAttribute('data-panel'));
                if (panel) panel.classList.add('active');
                if (tab.getAttribute('data-panel') === 'demo-timeline') renderTimeline();
            });
        });
    }

    // Demo record form
    function initDemoForm() {
        $('#demo-save-btn').addEventListener('click', function() {
            var topic = $('#demo-topic').value.trim();
            var progress = $('#demo-progress').value.trim();
            var difficulty = $('#demo-difficulty').value.trim();
            var nextStep = $('#demo-next').value.trim();
            var notes = $('#demo-notes').value.trim();
            var msgEl = $('#demo-msg');

            if (!topic) {
                showDemoMsg(msgEl, '请填写学习主题', 'error');
                return;
            }
            if (!progress && !difficulty && !nextStep && !notes) {
                showDemoMsg(msgEl, '请至少填写一项内容', 'error');
                return;
            }

            var records = loadRecords();
            var rec = {
                id: genId(),
                marker: MARKER,
                topic: topic,
                progress: progress,
                difficulty: difficulty,
                next_step: nextStep,
                notes: notes,
                created_at: new Date().toISOString()
            };
            records.push(rec);
            saveRecords(records);

            showDemoMsg(msgEl, '记录已保存（localStorage 模拟）', 'success');
            $('#demo-progress').value = '';
            $('#demo-difficulty').value = '';
            $('#demo-next').value = '';
            $('#demo-notes').value = '';
            updateTopicDatalist();
        });

        // Seed buttons
        $$('.demo-seed-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                $('#demo-topic').value = btn.getAttribute('data-topic');
            });
        });

        $('#demo-seed-all').addEventListener('click', function() {
            var samples = [
                { topic: '深度学习基础', progress: '完成了 CNN 卷积神经网络的基本原理学习', difficulty: '反向传播的链式求导过程还不够清晰', next_step: '动手实现一个简单的 CNN 分类器', notes: '参考了李宏毅老师的课程（样例虚构数据）' },
                { topic: '深度学习基础', progress: '实现了 MNIST 手写数字分类，训练集准确率 98.5%', difficulty: '过拟合问题：验证集准确率只有 95%', next_step: '学习正则化方法', notes: '代码已提交（样例虚构数据）' },
                { topic: '论文阅读 - Transformer', progress: '阅读了 Attention Is All You Need 的前半部分', difficulty: 'Multi-head attention 的拼接维度不太理解', next_step: '继续阅读论文后半部分', notes: '配合了图解 Transformer 博客（样例虚构数据）' },
                { topic: '论文阅读 - Transformer', progress: '读完整篇论文，理清了 encoder-decoder 架构', difficulty: '位置编码的数学推导还需要消化', next_step: '用 PyTorch 实现一个 mini Transformer', notes: '标注了需要复习的 3 个关键公式（样例虚构数据）' }
            ];
            var records = loadRecords();
            var baseTime = Date.now() - 86400000 * 3;
            samples.forEach(function(s, i) {
                records.push({
                    id: genId(),
                    marker: MARKER,
                    topic: s.topic,
                    progress: s.progress,
                    difficulty: s.difficulty,
                    next_step: s.next_step,
                    notes: s.notes,
                    created_at: new Date(baseTime + i * 3600000).toISOString()
                });
            });
            saveRecords(records);
            var msgEl = $('#demo-msg');
            showDemoMsg(msgEl, '已加载 4 条样例数据（虚构）', 'success');
            updateTopicDatalist();
        });
    }

    function showDemoMsg(el, text, type) {
        el.textContent = text;
        el.className = 'demo-msg ' + type;
        setTimeout(function() { el.className = 'demo-msg'; }, 4000);
    }

    function clearChildren(el) {
        while (el.firstChild) el.removeChild(el.firstChild);
    }

    function updateTopicDatalist() {
        var records = loadRecords();
        var topics = {};
        records.forEach(function(r) { topics[r.topic] = true; });
        var datalist = $('#demo-topic-list');
        clearChildren(datalist);
        Object.keys(topics).forEach(function(t) {
            var opt = document.createElement('option');
            opt.value = t;
            datalist.appendChild(opt);
        });
        updateFilterSelects();
    }

    function updateFilterSelects() {
        var records = loadRecords();
        var topics = {};
        records.forEach(function(r) { topics[r.topic] = true; });
        var topicList = Object.keys(topics).sort();

        var filterSel = $('#demo-filter-topic');
        var weeklySel = $('#demo-weekly-topic');
        [filterSel, weeklySel].forEach(function(sel) {
            var val = sel.value;
            clearChildren(sel);
            var defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = '全部主题';
            sel.appendChild(defaultOpt);
            topicList.forEach(function(t) {
                var opt = document.createElement('option');
                opt.value = t;
                opt.textContent = t;
                sel.appendChild(opt);
            });
            sel.value = val;
        });
    }

    // Timeline
    function renderTimeline() {
        var container = $('#demo-timeline-list');
        clearChildren(container);
        var topicFilter = $('#demo-filter-topic').value;
        var records = loadRecords();
        if (topicFilter) {
            records = records.filter(function(r) { return r.topic === topicFilter; });
        }
        records.sort(function(a, b) { return b.created_at.localeCompare(a.created_at); });

        if (records.length === 0) {
            var emptyDiv = document.createElement('div');
            emptyDiv.className = 'demo-empty';
            emptyDiv.textContent = '暂无记录';
            container.appendChild(emptyDiv);
            return;
        }
        records.forEach(function(rec) {
            var item = document.createElement('div');
            item.className = 'demo-tl-item';

            var dateDiv = document.createElement('div');
            dateDiv.className = 'demo-tl-date';
            dateDiv.textContent = rec.created_at.replace('T', ' ').substring(0, 16);
            item.appendChild(dateDiv);

            var topicDiv = document.createElement('div');
            topicDiv.className = 'demo-tl-topic';
            topicDiv.textContent = rec.topic;
            item.appendChild(topicDiv);

            var contentDiv = document.createElement('div');
            contentDiv.className = 'demo-tl-content';
            if (rec.progress) { contentDiv.appendChild(makeLabel('进展：')); contentDiv.appendChild(document.createTextNode(rec.progress)); contentDiv.appendChild(document.createElement('br')); }
            if (rec.difficulty) { contentDiv.appendChild(makeLabel('困难：')); contentDiv.appendChild(document.createTextNode(rec.difficulty)); contentDiv.appendChild(document.createElement('br')); }
            if (rec.next_step) { contentDiv.appendChild(makeLabel('下一步：')); contentDiv.appendChild(document.createTextNode(rec.next_step)); }
            item.appendChild(contentDiv);

            container.appendChild(item);
        });
    }

    function makeLabel(text) {
        var span = document.createElement('span');
        span.style.fontWeight = '500';
        span.textContent = text;
        return span;
    }

    // Weekly
    function initWeekly() {
        $('#demo-gen-weekly').addEventListener('click', function() {
            var topicFilter = $('#demo-weekly-topic').value;
            var records = loadRecords();
            if (topicFilter) {
                records = records.filter(function(r) { return r.topic === topicFilter; });
            }
            var output = generateWeeklyMarkdown(records, topicFilter);
            $('#demo-weekly-output').textContent = output;
        });
    }

    function generateWeeklyMarkdown(records, topic) {
        if (records.length === 0) {
            return '# 研途周报\n\n本周暂无学习记录。';
        }
        records.sort(function(a, b) { return a.created_at.localeCompare(b.created_at); });

        var byTopic = {};
        records.forEach(function(r) {
            if (!byTopic[r.topic]) byTopic[r.topic] = [];
            byTopic[r.topic].push(r);
        });

        var lines = [];
        lines.push('# 研途周报');
        lines.push('');
        lines.push('**周期：' + records[0].created_at.substring(0, 10) + ' ~ ' + records[records.length - 1].created_at.substring(0, 10) + '**');
        lines.push('');
        lines.push('共记录 **' + records.length + '** 条学习进展，涉及 **' + Object.keys(byTopic).length + '** 个主题。');
        lines.push('');

        var topicNames = Object.keys(byTopic).sort();
        topicNames.forEach(function(t) {
            if (topic && t !== topic) return;
            lines.push('## 主题：' + t);
            lines.push('');
            var recs = byTopic[t];
            var progresses = recs.filter(function(r) { return r.progress; });
            if (progresses.length > 0) {
                lines.push('### 进展');
                progresses.forEach(function(r) { lines.push('- ' + r.progress); });
                lines.push('');
            }
            var difficulties = recs.filter(function(r) { return r.difficulty; });
            if (difficulties.length > 0) {
                lines.push('### 困难');
                difficulties.forEach(function(r) { lines.push('- ' + r.difficulty); });
                lines.push('');
            }
            var nextSteps = recs.filter(function(r) { return r.next_step; });
            if (nextSteps.length > 0) {
                lines.push('### 下一步计划');
                nextSteps.forEach(function(r) { lines.push('- ' + r.next_step); });
                lines.push('');
            }
        });

        lines.push('---');
        lines.push('');
        lines.push('## 引用来源');
        lines.push('');
        records.forEach(function(r) {
            lines.push('- id: `' + r.id + '` | 时间: ' + r.created_at.substring(0, 19) + ' | 主题: ' + r.topic);
        });
        lines.push('');
        lines.push('---');
        lines.push('');
        lines.push('*本报告由研途 StudyFlow 演示生成（客户端 localStorage 模拟）。*');

        return lines.join('\n');
    }

    // Filter change
    function initFilters() {
        $('#demo-filter-topic').addEventListener('change', renderTimeline);
    }

    // Smooth scroll
    function initSmoothScroll() {
        $$('.header-nav a').forEach(function(a) {
            a.addEventListener('click', function(e) {
                e.preventDefault();
                var target = document.querySelector(a.getAttribute('href'));
                if (target) target.scrollIntoView({ behavior: 'smooth' });
            });
        });
    }

    // Init
    function init() {
        initTheme();
        initDemoTabs();
        initDemoForm();
        initWeekly();
        initFilters();
        initSmoothScroll();
        updateTopicDatalist();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
