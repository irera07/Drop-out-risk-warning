# Caude AI Web

A Flask web application for school dropout prediction using machine learning.

## Features

- User authentication for teachers, principals, and local leaders
- ML model for predicting student dropout risk
- Dashboards for different user roles
- Database integration with MySQL

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/caude-ai-web.git
   cd caude-ai-web
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up the database:
   - Create a MySQL database named `dropout_db`
   - Run the schema.sql file to create tables
   - Update the DB_URL in app.py or set environment variable

4. Place your trained model file at `model/dropout_model.joblib`

5. Run the application:
   ```bash
   python app.py
   ```

## Deployment

### GitHub
Push the code to GitHub:
```bash
git add .
git commit -m "Initial commit"
git push origin main
```

### Netlify
This application can be deployed on Netlify using serverless functions.

1. Create a new site on Netlify
2. Connect your GitHub repository
3. The netlify.toml file is configured for serverless deployment
4. For the database, use a hosted MySQL service like PlanetScale or AWS RDS, and set the DB_URL environment variable in Netlify
5. Place the model file in the model/ directory

Note: Netlify Functions are stateless, so ensure the database is hosted externally.

## Usage

- Register/Login as teacher, principal, or leader
- Access respective dashboards
- Use the ML model for predictions

## License

MIT License