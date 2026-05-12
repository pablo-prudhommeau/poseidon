const path = require('node:path');

module.exports = function configureKarma(config) {
    config.set({
        basePath: '',
        frameworks: ['jasmine'],
        plugins: [
            require('karma-jasmine'),
            require('karma-chrome-launcher'),
            require('karma-jasmine-html-reporter'),
            require('karma-coverage'),
        ],
        client: {
            clearContext: false,
        },
        jasmineHtmlReporter: {
            suppressAll: true,
        },
        coverageReporter: {
            dir: path.join(__dirname, './coverage/frontend'),
            subdir: '.',
            reporters: [
                { type: 'html' },
                { type: 'text-summary' },
            ],
        },
        reporters: ['progress', 'kjhtml'],
        browsers: ['ChromeHeadless'],
        customLaunchers: {
            ChromeHeadlessNoSandbox: {
                base: 'ChromeHeadless',
                flags: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
            },
        },
        restartOnFileChange: true,
    });
};
