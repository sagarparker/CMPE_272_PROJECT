pipeline {
    agent any
    options { timeout(time: 35, unit: 'MINUTES') }
    stages {
        stage('Checkout') { steps { checkout scm } }
        stage('Verify') { steps { sh './infra/check.sh' } }
        stage('Security gate') { steps { sh './infra/security-check.sh' } }
        stage('Build containers') { steps { sh 'docker compose build' } }
    }
    post {
        always {
            junit allowEmptyResults: true, testResults: 'backend/target/surefire-reports/*.xml'
            sh 'docker compose --profile test down'
        }
    }
}
