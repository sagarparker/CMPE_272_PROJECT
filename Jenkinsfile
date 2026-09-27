pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Verify Project') {
            steps {
                sh 'echo "Jenkins successfully checked out CMPE_272_PROJECT"'
                sh 'ls -la'
            }
        }
    }
}
