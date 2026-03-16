import { useNavigate } from 'react-router-dom';
import Logo from '../components/Logo';
import { 
  Type, 
  Save, 
  Upload, 
  Download, 
  Image, 
  Mic,
  Sparkles,
  Zap
} from 'lucide-react';
import logoImage from '../assets/notelite_icon.png';

export default function Landing() {
  const navigate = useNavigate();

  // const features = [
  //   {
  //     icon: Type,
  //     title: 'Rich Text Editor',
  //     description: ''
  //   },
  //   {
  //     icon: Save,
  //     title: 'Auto-save',
  //     description: 'Never lose your work'
  //   },
  //   {
  //     icon: Upload,
  //     title: 'Import Files',
  //     description: 'Upload .docx and .txt files'
  //   },
  //   {
  //     icon: Download,
  //     title: 'Export PDF',
  //     description: 'Download notes as PDFs'
  //   },
  //   {
  //     icon: Image,
  //     title: 'Media Support',
  //     description: 'Add images and videos'
  //   },
  //   {
  //     icon: Mic,
  //     title: 'Speech-to-Text',
  //     description: 'Convert your voice to text'
  //   }
  // ];


  const features = [
    {
      icon: Type,
      title: 'Rich Text Editor',
      description: 'Professional markdown editing with real-time preview, syntax highlighting, and intelligent formatting',
      color: 'from-blue-500 to-cyan-500',
      iconBg: 'bg-blue-50',
      iconColor: 'text-blue-600'
    },
    {
      icon: Save,
      title: 'Auto-Save',
      description: 'Your work is continuously saved in real-time. Focus on writing, we\'ll handle the rest',
      color: 'from-green-500 to-emerald-500',
      iconBg: 'bg-green-50',
      iconColor: 'text-green-600'
    },
    {
      icon: Upload,
      title: 'Import Files',
      description: 'Seamlessly import existing documents from .docx, .txt, and markdown files',
      color: 'from-purple-500 to-pink-500',
      iconBg: 'bg-purple-50',
      iconColor: 'text-purple-600'
    },
    {
      icon: Download,
      title: 'Export Anywhere',
      description: 'Export your notes as PDF, HTML, or markdown. Share your work in any format you need',
      color: 'from-orange-500 to-red-500',
      iconBg: 'bg-orange-50',
      iconColor: 'text-orange-600'
    },
    {
      icon: Image,
      title: 'Media Support',
      description: 'Embed images, videos, and links to create rich, multimedia documents',
      color: 'from-indigo-500 to-blue-500',
      iconBg: 'bg-indigo-50',
      iconColor: 'text-indigo-600'
    },
    {
      icon: Mic,
      title: 'Voice to Text',
      description: 'Transform your thoughts into text instantly with advanced speech recognition',
      color: 'from-pink-500 to-rose-500',
      iconBg: 'bg-pink-50',
      iconColor: 'text-pink-600'
    }
  ];

  return (
    <div className="min-h-screen bg-white text-gray-900">
      {/* Header */}
      <header className="">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <Logo size="xl" showText={true} />
            <div className="flex gap-4">
              <button
                onClick={() => navigate('/login')}
                className="px-6 py-2 border border-gray-900 rounded-md hover:bg-gray-100 transition-colors"
              >
                Login
              </button>
              <button
                onClick={() => navigate('/register')}
                className="px-6 py-2 bg-gray-900 text-white rounded-md hover:bg-gray-800 transition-colors"
              >
                Sign Up
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="py-20 border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-5xl font-bold mb-6">
            Your Notes, Simplified.
          </h2>
          <p className="text-xl text-gray-600 mb-10 max-w-2xl mx-auto">
            A Lightweight note-taking application with essential features.
            Simple, fast, and reliable.
          </p>
          <button
            onClick={() => navigate('/register')}
            className="px-8 py-4 bg-gray-900 text-white text-lg rounded-md hover:bg-gray-800 transition-colors"
          >
            Get Started Free
          </button>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h3 className="text-3xl font-bold text-center mb-12">
            Everything You Need
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {features.map((feature, index) => (
              <div
                key={index}
                className="p-6 border border-gray-200 rounded-md hover:scale-105 cursor-pointer transition-all"
              >

                <div className={`relative inline-flex items-center justify-center w-14 h-14 ${feature.iconBg} rounded-xl mb-5 group-hover:scale-110 transition-transform duration-300`}>
                  <feature.icon size={32} className={feature.iconColor} strokeWidth={2} />
                </div>
                <h4 className="text-xl font-bold mb-2 ">{feature.title}</h4>
                <p className="text-gray-600">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 bg-gray-900 text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h3 className="text-4xl font-bold mb-6">
            Ready to Get Started?
          </h3>
          <p className="text-xl text-gray-300 mb-10">
            Join NoteLite today and experience the simplicity of note-taking.
          </p>
          <button
            onClick={() => navigate('/register')}
            className="px-8 py-4 bg-white text-gray-900 text-lg rounded-md hover:bg-gray-100 transition-colors"
          >
            Create Free Account
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-1 bg-gray-900 text-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center font-light text-sm leading-7 tracking-wide">
          <span className="flex justify-center items-center gap-1">
            <span className="flex justify-center items-center -space-x-1">
              <img src={logoImage} alt="NoteLite Logo" className="w-7 h-7 rounded-full shadow-sm inline-block mr-1" />
              <span className="font-semibold">NoteLite</span>
              </span>
            <span>&copy; {new Date().getFullYear()}. All rights reserved.</span>
          </span>
        </div>
      </footer>
    </div>
  );
}

